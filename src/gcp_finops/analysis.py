"""Cost analysis on the flattened billing table (see schema.py).

Every function takes the DataFrame from schema.load_csv() and returns plain data,
so each one can be tested on a tiny hand-made table.

Conventions:
  * Money is reported as NET cost (gross cost + credits), because that is what the
    invoice charges. Gross cost is kept in the summary for context.
  * Month-over-month uses invoice_month, the month the charge is billed in, which is
    how finance teams reconcile. Grouping by usage date would split some charges
    differently around month boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Summary:
    currency: str
    start: pd.Timestamp
    end: pd.Timestamp
    gross: float
    credits: float
    net: float
    by_month: pd.DataFrame  # invoice_month, net_cost


def summarize(df: pd.DataFrame) -> Summary:
    currencies = df["currency"].unique()
    if len(currencies) != 1:
        raise ValueError(f"Expected one currency, found {list(currencies)}")
    by_month = df.groupby("invoice_month", as_index=False)["net_cost"].sum().sort_values("invoice_month")
    return Summary(
        currency=currencies[0],
        start=df["usage_start_time"].min(),
        end=df["usage_start_time"].max(),
        gross=round(df["cost"].sum(), 2),
        credits=round(df["credits"].sum(), 2),
        net=round(df["net_cost"].sum(), 2),
        by_month=by_month.round(2).reset_index(drop=True),
    )


def breakdown(df: pd.DataFrame, by: str | list[str], top: int | None = None) -> pd.DataFrame:
    """Net cost grouped by one or more columns, largest first, with each group's share."""
    keys = [by] if isinstance(by, str) else by
    out = df.groupby(keys, as_index=False)["net_cost"].sum().sort_values("net_cost", ascending=False)
    total = out["net_cost"].sum()
    out["share_pct"] = (out["net_cost"] / total * 100) if total else 0.0
    if top:
        out = out.head(top)
    return out.round(2).reset_index(drop=True)


def month_over_month(df: pd.DataFrame, by: str = "service") -> pd.DataFrame:
    """Compare the last two invoice months per group, biggest absolute change first.

    Assumes both months are complete. Run it on a partial month and every group will
    look like it dropped.
    """
    months = sorted(df["invoice_month"].unique())
    if len(months) < 2:
        raise ValueError("Need at least two invoice months to compare")
    prev_month, curr_month = months[-2], months[-1]

    pivot = (
        df[df["invoice_month"].isin([prev_month, curr_month])]
        .pivot_table(index=by, columns="invoice_month", values="net_cost", aggfunc="sum", fill_value=0.0)
        .reindex(columns=[prev_month, curr_month], fill_value=0.0)
    )
    out = pd.DataFrame(
        {
            by: pivot.index,
            "previous": pivot[prev_month].values,
            "current": pivot[curr_month].values,
        }
    )
    out["change"] = out["current"] - out["previous"]
    # Percent change is undefined for something that didn't exist last month.
    out["change_pct"] = out.apply(
        lambda r: (r["change"] / r["previous"] * 100) if r["previous"] else float("nan"), axis=1
    )
    out = out.reindex(out["change"].abs().sort_values(ascending=False).index)
    out.attrs["previous_month"], out.attrs["current_month"] = prev_month, curr_month
    return out.round(2).reset_index(drop=True)


@dataclass
class Allocation:
    required_labels: tuple[str, ...]
    allocated: float
    unallocated: float
    unallocated_pct: float
    gaps: pd.DataFrame  # project_id, sku, missing_labels, net_cost


def allocation(df: pd.DataFrame, required_labels: tuple[str, ...] = ("team", "env")) -> Allocation:
    """How much spend can be charged back to an owner?

    A row counts as allocated only if every required label is present and non-empty.
    Anything else is unallocated spend that nobody owns, which is usually where waste
    hides.
    """

    def missing(labels: dict) -> str:
        return ", ".join(k for k in required_labels if not labels.get(k))

    tagged = df.assign(missing_labels=df["labels"].map(missing))
    is_gap = tagged["missing_labels"] != ""
    total = tagged["net_cost"].sum()
    unallocated = tagged.loc[is_gap, "net_cost"].sum()

    gaps = (
        tagged[is_gap]
        .groupby(["project_id", "sku", "missing_labels"], as_index=False)["net_cost"]
        .sum()
        .sort_values("net_cost", ascending=False)
        .round(2)
        .reset_index(drop=True)
    )
    return Allocation(
        required_labels=required_labels,
        allocated=round(total - unallocated, 2),
        unallocated=round(unallocated, 2),
        unallocated_pct=round(unallocated / total * 100, 2) if total else 0.0,
        gaps=gaps,
    )
