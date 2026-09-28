"""Render the analysis as a Markdown report someone in finance or engineering can read."""

from __future__ import annotations

import math

import pandas as pd

from . import analysis


def _money(value: float, currency: str) -> str:
    symbol = "₹" if currency == "INR" else f"{currency} "
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.0f}"


def _pct(value: float) -> str:
    return "new" if value is None or (isinstance(value, float) and math.isnan(value)) else f"{value:+.1f}%"


def _month(yyyymm: str) -> str:
    return pd.Timestamp(f"{yyyymm[:4]}-{yyyymm[4:]}-01").strftime("%b %Y")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def build_report(df: pd.DataFrame, required_labels: tuple[str, ...] = ("team", "env"), top: int = 10) -> str:
    s = analysis.summarize(df)
    cur = s.currency
    by_project = analysis.breakdown(df, "project_id")
    by_service = analysis.breakdown(df, "service")
    by_sku = analysis.breakdown(df, ["service", "sku"], top=top)
    mom = analysis.month_over_month(df, "service")
    mom_project = analysis.month_over_month(df, "project_id")
    alloc = analysis.allocation(df, required_labels)

    out: list[str] = []
    out.append("# Cloud cost report")
    out.append(
        f"{s.start:%d %b %Y} to {s.end:%d %b %Y}. "
        f"Net cost **{_money(s.net, cur)}** (gross {_money(s.gross, cur)}, credits {_money(s.credits, cur)})."
    )

    out.append("## Key findings")
    top_mover = mom_project.iloc[0]
    findings = [
        f"**{alloc.unallocated_pct:.1f}%** of spend ({_money(alloc.unallocated, cur)}) is missing a required "
        f"label ({', '.join(required_labels)}) and can't be charged back to an owner.",
        f"Biggest project change {_month(mom.attrs['previous_month'])} → {_month(mom.attrs['current_month'])}: "
        f"**{top_mover['project_id']}** {_money(top_mover['change'], cur)} ({_pct(top_mover['change_pct'])}).",
        f"Largest project: **{by_project.iloc[0]['project_id']}**, {by_project.iloc[0]['share_pct']:.1f}% of spend.",
    ]
    out.append("\n".join(f"- {f}" for f in findings))

    out.append("## Net cost by month")
    out.append(_table(["Invoice month", "Net cost"], [[_month(m), _money(v, cur)] for m, v in s.by_month.itertuples(index=False)]))

    out.append("## By project")
    out.append(_table(["Project", "Net cost", "Share"],
                      [[p, _money(v, cur), f"{sh:.1f}%"] for p, v, sh in by_project.itertuples(index=False)]))

    out.append("## By service")
    out.append(_table(["Service", "Net cost", "Share"],
                      [[p, _money(v, cur), f"{sh:.1f}%"] for p, v, sh in by_service.itertuples(index=False)]))

    out.append(f"## Top {top} SKUs")
    out.append(_table(["Service", "SKU", "Net cost", "Share"],
                      [[sv, sk, _money(v, cur), f"{sh:.1f}%"] for sv, sk, v, sh in by_sku.itertuples(index=False)]))

    prev, curr = _month(mom.attrs["previous_month"]), _month(mom.attrs["current_month"])
    for title, table, key in (("service", mom, "service"), ("project", mom_project, "project_id")):
        out.append(f"## Month over month by {title} ({prev} → {curr})")
        out.append(_table([title.capitalize(), prev, curr, "Change", "%"],
                          [[r[key], _money(r["previous"], cur), _money(r["current"], cur),
                            _money(r["change"], cur), _pct(r["change_pct"])] for _, r in table.iterrows()]))

    out.append("## Cost allocation")
    out.append(
        f"Required labels: `{'`, `'.join(required_labels)}`. "
        f"Allocated {_money(alloc.allocated, cur)}, unallocated {_money(alloc.unallocated, cur)} "
        f"({alloc.unallocated_pct:.1f}%)."
    )
    if len(alloc.gaps):
        out.append(_table(["Project", "SKU", "Missing labels", "Net cost"],
                          [[p, sk, m, _money(v, cur)] for p, sk, m, v in alloc.gaps.itertuples(index=False)]))

    return "\n\n".join(out) + "\n"
