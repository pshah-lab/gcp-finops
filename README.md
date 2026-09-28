# gcp-finops

A tool that reads a Google Cloud bill and tells you where money is being wasted and what to do about it.

Cloud bills are long, and they're full of small leaks nobody notices: a forgotten test VM, a disk left
behind after its VM was deleted, an IP address reserved but never used, a machine far bigger than it
needs to be, a mistaken query that scanned terabytes. Each one is small. Together they add up every
month, and often nobody knows which team owns them. gcp-finops finds them in the Cloud Billing export
and reports what each one costs.

**[See an example report →](docs/example-report.md)** (generated from the bundled synthetic dataset)

**[Code walkthrough →](docs/CODE-WALKTHROUGH.md)**: how each file works, and the pros, cons and trade-offs of every design decision.

## Two rules

- **Read-only.** gcp-finops never changes or deletes anything in your cloud account; it only reads
  and reports. That makes it safe to point at any account.
- **Every number traces back to the bill.** Each figure in a report is a sum of billing export rows,
  so a finding can always be checked against the invoice.

## What it answers

| Question | Status |
|---|---|
| 1. Where does the money go? (by project, service and SKU) | ✅ Done |
| 2. What changed since last month? (biggest increases and drops) | ✅ Done |
| 3. Who owns the spend? (spend missing required labels such as `team` and `env`) | ✅ Done |
| 4. When did something go wrong? (the exact day of a cost spike) | Planned, Stage 2 |
| 5. What's being wasted? (idle VMs, unattached disks, unused static IPs, old snapshots) | Planned, Stage 2 |
| 6. What's oversized? (machines using far less than they pay for) | Planned, Stage 3 |

Today it runs offline on a billing CSV. Stage 2 connects it to a live billing export in BigQuery.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

gcp-finops sample     # writes data/sample_billing.csv (synthetic, seeded)
gcp-finops report     # writes reports/cost_report.md
pytest
```

Options: `gcp-finops report --input my.csv --labels team,env,cost-center --top 15`.

## Design decisions

**One flattened schema for every source.** The BigQuery billing export is nested (`service.description`,
`labels[]`, `credits[]`). `schema.py` defines a flat table once and documents where each column comes
from in the real export. The CSV loader produces it today, and the BigQuery loader will `SELECT` into
the same columns, so the analysis never depends on where the data came from.

**Net cost, not gross.** Credits (sustained-use discounts, committed-use discounts, free tier) are
negative amounts in the export. Net = `cost + SUM(credits.amount)` is what the invoice charges, so
every ranking uses net. Gross is still shown for context.

**Group months by `invoice.month`, not usage date.** That's how finance reconciles against the invoice.
Month-over-month assumes both months are complete; a partial month would make everything look like a
drop.

**Sort changes by absolute amount, not percent.** A project going from ₹10 to ₹100 is +900% but
irrelevant; a ₹40,000 project growing 12% matters more. Percent is shown, but the order is by rupees.
New items have no percentage, because change from zero is undefined.

**Allocation means every required label is present and non-empty.** Spend with a missing or blank
`team`/`env` label can't be charged back, and unowned spend is usually where waste hides. In the sample
data, the forgotten sandbox VM, unattached disk and idle static IP all show up here.

**Synthetic data with planted problems.** No real billing data is in this repo. `sample.py` generates
three months of seeded, reproducible data for a small company in `asia-south1`, billed in INR, with
issues planted on purpose: a staging environment that grows 35% a month, unlabelled sandbox resources,
and a one-day BigQuery spike. The tests check that the report finds them.

**Pure functions, tested by hand.** Each analysis function takes a DataFrame and returns data. The unit
tests use a seven-row table whose expected answers are worked out in the test file's docstring.

## Project layout

```
src/gcp_finops/
  schema.py     flattened billing schema + CSV loader
  sample.py     synthetic billing data generator
  analysis.py   summary, breakdowns, month-over-month, allocation
  report.py     Markdown report
  cli.py        `gcp-finops sample | report`
tests/          unit tests on a hand-checked table + end-to-end tests
docs/
  example-report.md     report generated from the synthetic data
  CODE-WALKTHROUGH.md   design, trade-offs and known limitations
.github/workflows/ci.yml   tests + sample report on Python 3.10 and 3.12
```

## Roadmap

- [x] **Stage 1:** offline analysis: breakdowns, month-over-month, cost allocation, tests, CI
- [ ] **Stage 2:** live data and waste
  - BigQuery loader for the Cloud Billing export, aggregating inside BigQuery and returning only
    summaries. Every query is dry-run first to estimate the bytes it will scan, and runs with a
    `maximum_bytes_billed` cap so an expensive query fails instead of costing money
  - Terraform for the billing dataset and a read-only service account
  - Daily anomaly detection: the exact day and service behind a spike
  - Waste finder: lists resources through the Compute Engine API (unattached disks, unused static IPs,
    old snapshots) and Google's idle-VM recommendations, then matches each one to the detailed billing
    export so every finding shows its monthly cost
- [ ] **Stage 3:** rightsizing and automation
  - Rightsizing from Cloud Monitoring p95 CPU and memory, compared with Google's Recommender API
  - HTML report alongside Markdown
  - Weekly scheduled run in GitHub Actions, authenticating with Workload Identity Federation, so no
    passwords or key files are stored

## License

MIT
