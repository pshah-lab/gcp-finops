# gcp-finops

Google Cloud cost analysis from Cloud Billing export data. It breaks down spend, shows what changed
month over month, and measures how much spend can't be charged back to an owner because labels are
missing.

**[See an example report →](docs/example-report.md)** (generated from the bundled synthetic dataset)

> Status: **Stage 1 of 3.** Works offline on a billing CSV. Next: a live BigQuery loader, waste
> detection (idle VMs, unattached disks, unused IPs), rightsizing from Cloud Monitoring, and daily
> anomaly detection. See the [roadmap](#roadmap).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

gcp-finops sample     # writes data/sample_billing.csv (synthetic, seeded)
gcp-finops report     # writes reports/cost_report.md
pytest
```

Options: `gcp-finops report --input my.csv --labels team,env,cost-center --top 15`.

## What the report answers

| Question | Section |
|---|---|
| What did we spend, before and after credits? | Summary, net cost by month |
| Where does the money go? | By project, by service, top SKUs |
| What changed since last month, and by how much? | Month over month by service and by project |
| How much spend has no owner? | Cost allocation: spend missing required labels, per project and SKU |

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
docs/           example report
```

## Roadmap

- [x] **Stage 1:** offline analysis, breakdowns, month-over-month, cost allocation, tests, CI
- [ ] **Stage 2:** BigQuery loader for a live billing export; Terraform for the dataset and a
      least-privilege service account; waste finder (unattached disks, unused static IPs, old
      snapshots, idle VMs); daily anomaly detection
- [ ] **Stage 3:** rightsizing from Cloud Monitoring p95 CPU and memory, cross-checked against the
      Recommender API; HTML report; scheduled GitHub Actions run

## License

MIT
