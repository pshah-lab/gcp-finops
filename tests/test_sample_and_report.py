"""End-to-end: the synthetic data loads, and the report finds the planted problems."""

from gcp_finops import analysis
from gcp_finops.report import build_report
from gcp_finops.sample import generate_rows, write_sample
from gcp_finops.schema import load_csv


def test_sample_is_deterministic():
    assert generate_rows(seed=7) == generate_rows(seed=7)
    assert generate_rows(seed=7) != generate_rows(seed=8)


def test_sample_round_trips_through_loader(tmp_path):
    path = tmp_path / "billing.csv"
    n = write_sample(path)
    df = load_csv(path)
    assert len(df) == n
    assert (df["credits"] <= 0).all()
    assert (df["net_cost"] <= df["cost"]).all()


def test_report_surfaces_planted_problems(tmp_path):
    path = tmp_path / "billing.csv"
    write_sample(path)
    df = load_csv(path)

    # Staging grows 35% a month and the sandbox appears in July, so both show up as movers.
    movers = analysis.month_over_month(df, "project_id").set_index("project_id")
    assert movers.loc["shop-staging", "change_pct"] > 25
    # The unlabelled sandbox must be flagged in allocation gaps.
    gaps = analysis.allocation(df).gaps
    assert "sandbox-pratham" in set(gaps["project_id"])

    text = build_report(df)
    assert text.startswith("# Cloud cost report")
    assert "## Cost allocation" in text
    assert "sandbox-pratham" in text
