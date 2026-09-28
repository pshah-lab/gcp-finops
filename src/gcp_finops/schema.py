"""The one table every analysis works on.

Google's Cloud Billing "standard usage cost" export to BigQuery has nested fields
(service.description, sku.description, labels[], credits[] ...). We flatten it once,
here, into plain columns. The offline CSV uses the same columns, and the future
BigQuery loader will SELECT into them too, so the analysis code never needs to know
where the data came from.

Reference: https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

# Flattened column  ->  where it comes from in the real BigQuery export
COLUMNS: dict[str, str] = {
    "usage_start_time": "usage_start_time (TIMESTAMP)",
    "invoice_month": "invoice.month (YYYYMM string)",
    "project_id": "project.id",
    "service": "service.description, e.g. 'Compute Engine'",
    "sku": "sku.description, e.g. 'E2 Instance Core running in Mumbai'",
    "region": "location.region",
    "labels": "labels[] (resource labels) as a JSON object, e.g. {\"team\": \"web\"}",
    "cost": "cost (gross, before credits)",
    "credits": "SUM(credits[].amount) (credits are negative numbers)",
    "currency": "currency",
    "usage_amount": "usage.amount_in_pricing_units",
    "usage_unit": "usage.pricing_unit",
}


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a flattened billing CSV and validate it against COLUMNS."""
    df = pd.read_csv(path, dtype={"invoice_month": str})
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")

    df["usage_start_time"] = pd.to_datetime(df["usage_start_time"], utc=True)
    df["labels"] = df["labels"].fillna("{}").map(json.loads)
    df["credits"] = df["credits"].fillna(0.0)
    # Net cost is what the customer actually pays: gross cost plus (negative) credits.
    df["net_cost"] = df["cost"] + df["credits"]
    return df
