# Code walkthrough: how gcp-finops works, and why

This document explains the Stage 1 code file by file, then goes through every significant design
decision with its pros, cons and the trade-off we accepted. The last section lists known limitations
and the questions an interviewer is likely to ask.

Read the code alongside it, in this order: `schema.py` → `analysis.py` → `report.py` → `sample.py`
→ `cli.py` → `tests/`.

---

## 1. The big picture

```
            ┌────────────────────┐
 CSV file ─►│ schema.load_csv()  │──┐
            └────────────────────┘  │   one flat DataFrame
 (Stage 2)  ┌────────────────────┐  ├─► (same columns, always) ─► analysis.* ─► report.build_report() ─► Markdown
 BigQuery ─►│ load_bigquery()    │──┘
            └────────────────────┘

 sample.write_sample() creates a synthetic CSV so the tool runs with no GCP account.
 cli.main() wires it together: `gcp-finops sample` and `gcp-finops report`.
```

The design has three layers, and each one only talks to the next:

| Layer | Files | Job | Knows about |
|---|---|---|---|
| Input | `schema.py`, `sample.py` | Get billing data into one flat table | Where the data comes from |
| Logic | `analysis.py` | Compute numbers | Only the flat table |
| Output | `report.py`, `cli.py` | Turn numbers into a document and a command | Only the analysis results |

The benefit: adding BigQuery in Stage 2 means writing one new loader. Nothing in `analysis.py` or
`report.py` changes.

---

## 2. File by file

### `schema.py`: the contract

**What it does.** Defines `COLUMNS`, the 12 flat columns every analysis relies on, and maps each one
to where it lives in Google's real billing export. `load_csv()` reads a CSV, checks that every column
exists, then cleans it:

- `usage_start_time` is parsed as a UTC timestamp.
- `invoice_month` is read as a **string** (`dtype={"invoice_month": str}`). Otherwise pandas would
  turn `"202608"` into the integer `202608`, and sorting or formatting would get fragile.
- `labels` is parsed from a JSON string into a Python dict. Missing labels become `{}`.
- `credits` missing becomes `0.0`.
- It adds the derived column `net_cost = cost + credits`.

**Key idea.** Google's export is nested: `service.description`, an array `labels[]` of key/value
pairs, and an array `credits[]`. We flatten it once, at the edge, so the rest of the code works on
simple columns.

### `analysis.py`: the logic

Four pure functions. Each takes the DataFrame and returns data without printing or writing files.

**`summarize(df) -> Summary`**
- Refuses to run if the data contains more than one currency, because adding ₹ and $ is meaningless.
- Returns gross cost, total credits, net cost, the date range and net cost per `invoice_month`.
- `Summary` is a `@dataclass`: a typed container, clearer than returning a loose dict.

**`breakdown(df, by, top=None)`**
- `groupby(by)` → sum `net_cost` → sort largest first → add `share_pct` (each group's percent of the
  total).
- `by` can be one column (`"project_id"`) or several (`["service", "sku"]`).
- The share is computed **before** `top` is applied, so a top-10 list still shows each SKU's share of
  the whole bill, not of the top 10.

**`month_over_month(df, by="service")`**
- Finds the last two invoice months present in the data.
- Uses `pivot_table` to get one row per group, with one column for each month. `fill_value=0.0`
  means a project that didn't exist last month shows ₹0 rather than disappearing.
- Adds `change` (current − previous) and `change_pct`. `change_pct` is `NaN` when the previous month
  was 0, because a percent change from zero is undefined. The report prints this as "new".
- Sorts by the **absolute** value of `change`, so big drops rank as high as big increases.
- Stores which months were compared in `out.attrs` so the report can label its columns.

**`allocation(df, required_labels=("team", "env")) -> Allocation`**
- For each row, lists which required labels are missing or empty. `labels.get(k)` returns `None` for
  a missing key and `""` for an empty value, and both count as missing.
- Rows with anything missing are unallocated: nobody can be charged for them.
- Returns totals, the unallocated percentage, and a `gaps` table grouped by project, SKU and which
  labels are missing, largest first. That table is effectively a to-do list for fixing labels.

### `report.py`: the presentation

- `_money()` formats amounts as `₹123,456` (international digit grouping, not Indian lakh
  grouping; see limitations). Negative values get a leading minus: `-₹16,969`.
- `_pct()` prints `+12.5%`, or `new` for `NaN`.
- `_month()` turns `"202608"` into `"Aug 2026"`.
- `_table()` builds a Markdown table by hand, so there's no extra dependency.
- `build_report()` calls every analysis function once, then assembles sections: key findings first
  (for a reader who stops after three lines), then detail tables.

### `sample.py`: the synthetic data

- `LineItem` describes one recurring daily charge: project, service, SKU, daily usage, unit price,
  labels, a credit rate (to mimic sustained-use discounts), monthly growth, and a start date.
- `LINE_ITEMS` defines a small company with problems planted on purpose:

| Planted problem | How | Where the report catches it |
|---|---|---|
| Staging keeps growing | `monthly_growth=0.35` on shop-staging | Month-over-month by project |
| Forgotten sandbox | VM, disk and static IP with no labels, starting 3 July | Cost allocation gaps |
| Runaway BigQuery query | `SPIKE_DAY` adds 18 TiB scanned on 19 Aug | BigQuery +118% month over month (Stage 2 will pinpoint the day) |
| Missing labels | Staging RAM has no labels; Nearline storage has no `env` | Cost allocation gaps |

- `generate_rows(seed)` uses `random.Random(seed)`, a private random generator. The same seed always
  gives the same data, which tests rely on.
- Day-to-day noise of ±8% (`rng.uniform(0.92, 1.08)`) makes the data look realistic without hiding
  the planted patterns.
- Output uses the same columns as `schema.COLUMNS`, so it flows through the real loader.

### `cli.py`: the command

`argparse` subcommands: `sample` writes the CSV and `report` reads a CSV and writes Markdown. The
`--labels` flag lets a company choose its own required labels (e.g. `team,env,cost-center`).
`pyproject.toml` registers `gcp-finops = "gcp_finops.cli:main"`, which is why the command exists
after `pip install -e .`.

### `tests/`

- **`test_analysis.py`** uses a seven-row table. Its docstring shows the expected answers worked out
  by hand (total net = 360, sandbox moved +40, 170 of 360 unallocated...). The tests check the
  code's answers against that arithmetic.
- **`test_sample_and_report.py`** checks the generator is deterministic, the sample survives a
  write → load round trip, and the report actually finds the planted problems.

### Supporting files

- `pyproject.toml`: package metadata, the one runtime dependency (pandas), pytest as a dev
  dependency, and the `src/` layout.
- `.github/workflows/ci.yml`: runs the tests and the sample report on Python 3.10 and 3.12 on every
  push.
- `.gitignore`: excludes `data/`, `reports/` and service-account keys, so real billing data or
  credentials can't be committed by accident.

---

## 3. Decisions, pros and cons, and trade-offs

### 3.1 Flatten the export into one schema

**Decision.** Convert the nested BigQuery export into 12 flat columns before any analysis.

| Pros | Cons |
|---|---|
| Analysis code is simple and doesn't care about the data source | We drop fields we might want later (e.g. `sku.id`, `project.labels`, `credits[].type`) |
| One place to update if Google changes the export | Flattening `credits[]` into one sum loses detail (see 3.9) |
| CSV and BigQuery become interchangeable | The schema is our own, so it needs documenting (done in `COLUMNS`) |

**Trade-off.** Simplicity now, over completeness. Adding a column later is cheap: extend `COLUMNS`,
the loader and the generator.

### 3.2 pandas in Python, instead of SQL in BigQuery

**Decision.** Do the analysis in pandas, in memory.

| Pros | Cons |
|---|---|
| Runs offline with no cloud account or cost | Everything must fit in memory; large companies' exports have millions of rows per month |
| Easy to unit-test with a tiny table | Pulling raw rows out of BigQuery costs query money and time |
| pandas is the common language of data work | Duplicates things BigQuery does natively (GROUP BY) |

**Trade-off.** Fine for Stage 1 and small accounts. In Stage 2 the right move is to push the heavy
aggregation (sum by project, service, SKU and month) into a BigQuery SQL query and pull back only the
aggregated rows, then let pandas do the rest. The flat schema makes that change local to the loader.

### 3.3 Report net cost, not gross

**Decision.** Rank and compare everything by `net_cost = cost + credits`.

| Pros | Cons |
|---|---|
| Matches the invoice, which is what finance cares about | Hides how much discount a service gets; a heavily discounted service can look cheap |
| Avoids overstating the cost of discounted resources | If a discount expires, net cost jumps with no usage change, which could be misread |

**Trade-off.** Net for decisions, gross shown in the summary for context. A future improvement is a
"credits by type" table so discount changes are visible.

### 3.4 Group months by `invoice.month`, not usage date

**Decision.** Month-over-month compares invoice months.

| Pros | Cons |
|---|---|
| Reconciles with the actual invoice | A charge used on 31 July can be billed in August, which blurs engineering timelines |
| Standard practice in FinOps reporting | Doesn't tell engineers exactly *when* usage changed |

**Trade-off.** Invoice month for money questions. For "what happened when" questions (Stage 2's daily
anomaly detection), use `usage_start_time`.

### 3.5 Month-over-month compares the last two months present

**Decision.** Automatically pick the two most recent invoice months.

| Pros | Cons |
|---|---|
| Zero configuration | If the latest month is incomplete, everything looks like it dropped |
| Always shows the most recent change | Can't compare arbitrary months (e.g. year over year) |

**Trade-off.** Convenience now; documented in the docstring. A `--months` flag, or excluding the
current partial month automatically, would fix it.

### 3.6 Sort changes by rupees, not percent

**Decision.** Order month-over-month tables by absolute change.

| Pros | Cons |
|---|---|
| The biggest money problems come first | A small service tripling in cost (an early warning) sinks to the bottom |
| Avoids tiny items dominating with huge percentages | |

**Trade-off.** Money impact first, because that's what gets acted on. Both columns are shown, so a
reader can still spot a large percentage.

### 3.7 "New" instead of a percentage when last month was zero

**Decision.** `change_pct` is `NaN` and printed as "new".

| Pros | Cons |
|---|---|
| Mathematically honest; no division by zero or fake "∞%" | Consumers of the data must handle `NaN` |

### 3.8 Allocation uses resource labels only, and requires all of them

**Decision.** A row is allocated only if every required label exists on the resource and is non-empty.

| Pros | Cons |
|---|---|
| Strict: forces good hygiene, and gaps are specific and fixable | Many companies label at the **project** level; we ignore `project.labels`, so their spend would look unallocated |
| Easy to explain | No partial credit: a resource with `team` but no `env` counts as fully unallocated |

**Trade-off.** Strictness and simplicity. The natural next step is a fallback: use the resource
label, else inherit from the project's labels. It's a small change in `allocation()` once
`project_labels` is added to the schema.

### 3.9 Credits summed into one number

**Decision.** `credits = SUM(credits[].amount)`.

| Pros | Cons |
|---|---|
| Simple and correct for net cost | Loses the credit type: sustained-use, committed-use, promotional and free tier look the same |

**Trade-off.** Enough for Stage 1. If commitment utilisation matters (a common FinOps question),
`credits[].type` needs its own column or table.

### 3.10 Labels stored as a JSON string in the CSV

**Decision.** `{"team": "web", "env": "prod"}` in one CSV cell, parsed on load.

| Pros | Cons |
|---|---|
| Keeps any number of labels in one column | Not human-friendly in a spreadsheet |
| Mirrors the key/value nature of the real export | Parsing cost on load (negligible at this size) |

Alternative considered: one column per label (`label_team`, `label_env`). That's spreadsheet-friendly
but breaks as soon as a company uses a label we didn't anticipate.

### 3.11 Floats for money, rounded at the end

**Decision.** Use floats and round to 2 decimals in outputs.

| Pros | Cons |
|---|---|
| Fast, simple, and what pandas and BigQuery return | Floats can't represent every decimal exactly; tiny errors can accumulate |
| Errors are far below a rupee at this scale | Not acceptable for actual invoicing or accounting |

**Trade-off.** This is an analysis tool, not a billing system, so paisa-level float error doesn't
change any decision. A billing system would use `Decimal` or integer paise.

### 3.12 Synthetic data instead of real data

**Decision.** Generate seeded fake data with planted problems.

| Pros | Cons |
|---|---|
| No confidential data in a public repo | Doesn't prove the tool works on real exports |
| Anyone can run it with no GCP account | Prices are approximate, and hourly granularity is simplified to daily rows |
| Tests can check that known problems are found | A reviewer might mistake it for real results; mitigated by labels on the example report |

**Trade-off.** Accessibility and safety now. Stage 2 adds a live BigQuery run against your own small
project, which answers the "does it work on real data" question.

### 3.13 Markdown report instead of a dashboard

**Decision.** Output a Markdown file.

| Pros | Cons |
|---|---|
| Readable on GitHub and in any editor, and easy to diff between runs | No charts or interactivity |
| Zero extra dependencies | Hand-built tables don't escape `|` characters in SKU names |
| Can be emailed, committed or pasted into a ticket | Not what executives usually expect (Looker Studio or Grafana) |

**Trade-off.** Portability over polish. Stage 3 plans an HTML report; a Looker Studio template on the
same BigQuery tables is another option.

### 3.14 Pure functions and dataclasses

**Decision.** Analysis functions take data and return data, with no I/O inside.

| Pros | Cons |
|---|---|
| Each function can be tested with a tiny table | The report calls several functions that each group the same data, so there's some repeated work |
| Easy to reuse from a notebook, an API or a scheduled job | Slightly more code than one big script |

**Trade-off.** Testability and clarity over a small amount of duplicate computation, which is
irrelevant at this data size.

### 3.15 Hand-checked tests

**Decision.** Unit tests use a seven-row table with answers computed by hand in the docstring.

| Pros | Cons |
|---|---|
| Tests verify the *logic*, not just "the code runs" | Small tables can miss edge cases that appear at scale |
| The docstring doubles as documentation of the maths | Adding columns to the schema means updating the fixture |

### 3.16 Tooling choices

| Choice | Why | Alternative |
|---|---|---|
| `argparse` | Standard library, no dependency | `click` or `typer`: nicer help text, extra dependency |
| `src/` layout + `pyproject.toml` | Tests run against the installed package, catching packaging mistakes | Flat layout: simpler, but can hide import bugs |
| One dependency (pandas) | Small install, less to maintain | Adding `tabulate` for tables, `jinja2` for HTML later |
| CI on Python 3.10 and 3.12 | Oldest supported and a current version | A full matrix would be slower for little gain |

---

## 4. Known limitations (honest list)

1. **Memory-bound.** All rows are loaded into pandas. Real exports need aggregation in BigQuery first
   (Stage 2).
2. **Partial months** distort month-over-month.
3. **Project labels ignored** in allocation.
4. **Credit types merged** into one number.
5. **Markdown tables don't escape `|`**, so a SKU name containing a pipe would break a table.
6. **Rupee formatting** uses international grouping (`₹123,456`) rather than Indian lakh grouping
   (`₹1,23,456`).
7. **Single currency only.** Multi-currency billing accounts need `currency_conversion_rate` from the
   export.
8. **Synthetic prices are approximate.** Don't quote them as real GCP prices.

Each of these is a good answer to "what would you improve?"

---

## 5. Questions to be ready for

**"Why net cost instead of gross?"**
Net is what the invoice charges. Gross overstates discounted services. I show gross in the summary
for context.

**"Why `invoice.month` and not usage date?"**
Finance reconciles by invoice month. For "when did this change" questions I'd use usage dates, which
is what the daily anomaly detection will do.

**"How would this scale to a company with millions of billing rows?"**
Push aggregation into BigQuery with SQL (`GROUP BY project, service, sku, invoice_month`) and bring
back only summaries. The flat schema means only the loader changes.

**"Why is BigQuery +118% in the example?"**
One day with an 18 TiB runaway query. The monthly total shows *that* something happened; daily
anomaly detection will show *when*. It's also why month totals alone can mislead.

**"What does unallocated spend tell you?"**
Spend nobody owns can't be charged back, and it's where forgotten resources hide. In the sample, the
forgotten sandbox VM, unattached disk and idle static IP all appear there.

**"Why synthetic data?"**
It keeps confidential billing data out of a public repo, lets anyone run the tool, and lets the tests
check that planted problems are found. Stage 2 runs it on a real (small) GCP project.

**"Why pandas and not just SQL?"**
It runs offline and is easy to unit-test. At scale I'd split the work: SQL in BigQuery for heavy
aggregation, pandas for the final shaping and report.

**"What would you do next?"**
BigQuery loader, then a waste finder (idle VMs, unattached disks, unused IPs), then rightsizing
from Cloud Monitoring p95 CPU and memory, checked against Google's Recommender API.
