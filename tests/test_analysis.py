"""Analysis tests on a table small enough to check by hand.

Rows (net = cost + credits):
  May  web-prod   Compute  team=web,env=prod   cost 100, credits -20  -> net  80
  May  web-prod   Storage  team=web,env=prod   cost  20                -> net  20
  May  sandbox    Compute  (no labels)         cost  50                -> net  50
  Jun  web-prod   Compute  team=web,env=prod   cost 100, credits -20  -> net  80
  Jun  web-prod   Storage  team=web            cost  30                -> net  30   (missing env)
  Jun  sandbox    Compute  (no labels)         cost  90                -> net  90
  Jun  new-proj   BigQuery team=data,env=dev   cost  10                -> net  10   (new in June)
Total net = 360.
"""

import math

import pandas as pd
import pytest

from gcp_finops import analysis


def row(month, project, service, labels, cost, credits=0.0):
    return {
        "usage_start_time": pd.Timestamp(f"{month[:4]}-{month[4:]}-01", tz="UTC"),
        "invoice_month": month,
        "project_id": project,
        "service": service,
        "sku": f"{service} SKU",
        "region": "asia-south1",
        "labels": labels,
        "cost": cost,
        "credits": credits,
        "net_cost": cost + credits,
        "currency": "INR",
        "usage_amount": 1.0,
        "usage_unit": "hour",
    }


@pytest.fixture
def df():
    prod = {"team": "web", "env": "prod"}
    return pd.DataFrame(
        [
            row("202605", "web-prod", "Compute", prod, 100, -20),
            row("202605", "web-prod", "Storage", prod, 20),
            row("202605", "sandbox", "Compute", {}, 50),
            row("202606", "web-prod", "Compute", prod, 100, -20),
            row("202606", "web-prod", "Storage", {"team": "web"}, 30),
            row("202606", "sandbox", "Compute", {}, 90),
            row("202606", "new-proj", "BigQuery", {"team": "data", "env": "dev"}, 10),
        ]
    )


def test_summary_nets_credits(df):
    s = analysis.summarize(df)
    assert s.gross == 400
    assert s.credits == -40
    assert s.net == 360
    assert s.by_month["net_cost"].tolist() == [150, 210]


def test_summary_rejects_mixed_currency(df):
    df.loc[0, "currency"] = "USD"
    with pytest.raises(ValueError):
        analysis.summarize(df)


def test_breakdown_orders_by_cost_with_share(df):
    b = analysis.breakdown(df, "project_id")
    assert b["project_id"].tolist() == ["web-prod", "sandbox", "new-proj"]
    assert b["net_cost"].tolist() == [210, 140, 10]
    assert b["share_pct"].tolist() == [58.33, 38.89, 2.78]


def test_breakdown_top_n(df):
    assert len(analysis.breakdown(df, "service", top=2)) == 2


def test_month_over_month_sorts_by_absolute_change(df):
    mom = analysis.month_over_month(df, "project_id")
    assert mom.attrs["previous_month"] == "202605"
    assert mom.attrs["current_month"] == "202606"
    # sandbox +40, new-proj +10, web-prod +10 (100 -> 110); sandbox moved most
    first = mom.iloc[0]
    assert first["project_id"] == "sandbox"
    assert (first["previous"], first["current"], first["change"]) == (50, 90, 40)
    assert first["change_pct"] == 80


def test_month_over_month_new_item_has_no_percentage(df):
    mom = analysis.month_over_month(df, "project_id").set_index("project_id")
    assert mom.loc["new-proj", "previous"] == 0
    assert math.isnan(mom.loc["new-proj", "change_pct"])


def test_month_over_month_needs_two_months(df):
    with pytest.raises(ValueError):
        analysis.month_over_month(df[df["invoice_month"] == "202606"])


def test_allocation_counts_missing_labels(df):
    a = analysis.allocation(df, ("team", "env"))
    # Unallocated: sandbox 50 + 90, web-prod storage in June 30 = 170 of 360
    assert a.unallocated == 170
    assert a.allocated == 190
    assert a.unallocated_pct == pytest.approx(47.22)
    gaps = a.gaps.set_index(["project_id", "missing_labels"])["net_cost"]
    assert gaps[("sandbox", "team, env")] == 140
    assert gaps[("web-prod", "env")] == 30


def test_allocation_treats_empty_label_value_as_missing(df):
    df.at[0, "labels"] = {"team": "web", "env": ""}
    a = analysis.allocation(df, ("team", "env"))
    assert a.unallocated == 170 + 80
