"""Synthetic billing data in the flattened export schema (see schema.py).

This is NOT real billing data. It models a small company on Google Cloud in
asia-south1 (Mumbai), billed in INR, over three months, with problems planted on
purpose so the analysis has something to find:

  * shop-staging grows every month (someone scaled it up and never scaled back)
  * sandbox-pratham has a forgotten VM, an unattached disk and an idle static IP,
    none of them labelled
  * data-pipeline has one day with a large BigQuery spike (a runaway query)
  * some spend is missing the `team` / `env` labels needed for cost allocation

Prices are rough, rounded INR figures for illustration only.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .schema import COLUMNS

START = date(2026, 6, 1)
END = date(2026, 8, 31)  # inclusive


@dataclass
class LineItem:
    """One recurring daily charge: a SKU used by a resource in a project."""

    project_id: str
    service: str
    sku: str
    daily_usage: float  # in pricing units per day
    unit: str
    unit_price_inr: float
    labels: dict[str, str] = field(default_factory=dict)
    credit_rate: float = 0.0  # e.g. 0.2 = 20% sustained-use discount
    monthly_growth: float = 0.0  # 0.25 = usage grows 25% each month
    starts: date = START


LINE_ITEMS: list[LineItem] = [
    # --- shop-prod: well labelled, steady ---
    LineItem("shop-prod", "Compute Engine", "N2 Instance Core running in Mumbai", 8 * 24, "hour", 3.1,
             {"team": "web", "env": "prod"}, credit_rate=0.2),
    LineItem("shop-prod", "Compute Engine", "N2 Instance Ram running in Mumbai", 32 * 24, "gibibyte hour", 0.42,
             {"team": "web", "env": "prod"}, credit_rate=0.2),
    LineItem("shop-prod", "Cloud SQL", "Cloud SQL for PostgreSQL: Zonal - vCPU in Mumbai", 4 * 24, "hour", 3.6,
             {"team": "web", "env": "prod"}),
    LineItem("shop-prod", "Cloud Storage", "Standard Storage Mumbai", 500 / 30, "gibibyte month", 1.9,
             {"team": "web", "env": "prod"}),
    LineItem("shop-prod", "Networking", "Network Internet Data Transfer Out from Mumbai", 40, "gibibyte", 7.5,
             {"team": "web", "env": "prod"}),
    # --- shop-staging: grows 35% a month, half of it unlabelled ---
    LineItem("shop-staging", "Compute Engine", "E2 Instance Core running in Mumbai", 4 * 24, "hour", 2.2,
             {"team": "web", "env": "staging"}, monthly_growth=0.35),
    LineItem("shop-staging", "Compute Engine", "E2 Instance Ram running in Mumbai", 16 * 24, "gibibyte hour", 0.3,
             {}, monthly_growth=0.35),
    # --- data-pipeline: BigQuery analysis + storage ---
    LineItem("data-pipeline", "BigQuery", "Analysis", 0.4, "tebibyte", 520.0,
             {"team": "data", "env": "prod"}),
    LineItem("data-pipeline", "BigQuery", "Active Logical Storage", 800 / 30, "gibibyte month", 1.7,
             {"team": "data", "env": "prod"}),
    LineItem("data-pipeline", "Cloud Storage", "Nearline Storage Mumbai", 2000 / 30, "gibibyte month", 0.85,
             {"team": "data"}),
    # --- sandbox-pratham: forgotten resources, no labels (starts in July) ---
    LineItem("sandbox-pratham", "Compute Engine", "E2 Instance Core running in Mumbai", 2 * 24, "hour", 2.2,
             {}, starts=date(2026, 7, 3)),
    LineItem("sandbox-pratham", "Compute Engine", "Storage PD Capacity in Mumbai", 200 / 30, "gibibyte month", 3.4,
             {}, starts=date(2026, 7, 3)),
    LineItem("sandbox-pratham", "Compute Engine", "Static Ip Charge", 24, "hour", 0.42,
             {}, starts=date(2026, 7, 3)),
]

# A runaway BigQuery job: 18 TiB scanned in one day.
SPIKE_DAY = date(2026, 8, 19)
SPIKE_EXTRA_TIB = 18.0


def _months_since_start(day: date) -> int:
    return (day.year - START.year) * 12 + day.month - START.month


def generate_rows(seed: int = 42) -> list[dict]:
    """Return one row per line item per day, in the flattened schema."""
    rng = random.Random(seed)
    rows: list[dict] = []
    day = START
    while day <= END:
        for item in LINE_ITEMS:
            if day < item.starts:
                continue
            usage = item.daily_usage * (1 + item.monthly_growth) ** _months_since_start(day)
            usage *= rng.uniform(0.92, 1.08)  # day-to-day noise
            if item.sku == "Analysis" and day == SPIKE_DAY:
                usage += SPIKE_EXTRA_TIB
            cost = round(usage * item.unit_price_inr, 2)
            rows.append(
                {
                    "usage_start_time": datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat(),
                    "invoice_month": f"{day.year}{day.month:02d}",
                    "project_id": item.project_id,
                    "service": item.service,
                    "sku": item.sku,
                    "region": "asia-south1",
                    "labels": json.dumps(item.labels, sort_keys=True),
                    "cost": cost,
                    "credits": -round(cost * item.credit_rate, 2),
                    "currency": "INR",
                    "usage_amount": round(usage, 4),
                    "usage_unit": item.unit,
                }
            )
        day += timedelta(days=1)
    return rows


def write_sample(path: str | Path, seed: int = 42) -> int:
    """Write the synthetic dataset to CSV. Returns the number of rows."""
    rows = generate_rows(seed)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
