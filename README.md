# ChainTrace

A read-only blockchain transaction investigation and evidence-reporting toolkit.
Load transfer data, explore address-to-address flows, build a case timeline, surface
transparent heuristic leads, and export a reproducible report in which every statement
points to the transactions behind it.

> **Safety model.** ChainTrace never creates transactions, signs anything, or asks for
> private keys. Heuristic output is a *lead*, not a verdict. Graph proximity is not proof of
> identity, criminality, or common ownership, and the tool never attributes an address to a
> named person. The bundled dataset is **entirely synthetic**.

## Features

| Area | What you get |
|---|---|
| Import | CSV import with strict validation. Bad rows are returned with line numbers and reasons, never silently dropped. SHA-256 of each import is logged. |
| Cases | SQLite case records: imports, notes, hypotheses (status + confidence), watchlist, analysis runs. |
| Graph | Directed NetworkX/Plotly graph. Filters: time window, asset, transfer value, hop depth and direction from a seed address. |
| Timeline | Chronological table: block, timestamp, tx hash, sender, recipient, amount, asset, data source, evidence ref, indicator tags. |
| Heuristics | Transaction bursts, unusual value changes, rapid multi-hop forwarding, repeated interactions with selected addresses. Every rule and threshold is shown with each indicator. |
| Evidence model | **Observed facts** vs **derived indicators** vs **investigator hypotheses**, kept in separate report sections. |
| Export | JSON, CSV (findings + evidence), self-contained HTML (print to PDF from a browser). `verify` re-derives a report from the data. |
| Data sources | Default CSV/synthetic adapter. Optional read-only public-explorer adapter (no API key; experimental). |

## Quick start (Windows PowerShell)

Requires Python 3.11+ (`py -3.11 --version` to check).

```powershell
cd chaintrace
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
# If activation is blocked:  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install --upgrade pip
pip install -e ".[dev]"

pytest -q                               # run the test suite
python -m chaintrace demo --out out\demo   # headless end-to-end sample case
streamlit run src\chaintrace\app.py        # launch the UI (http://localhost:8501)
```

macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, then the same pip/pytest/streamlit commands.

The UI stores cases in `chaintrace_cases.db` in the working directory. To use another location in PowerShell, set `$env:CHAINTRACE_DB = "$PWD\cases\my.db"`; missing parent folders on an existing drive are created automatically. If the database still cannot be opened, check that its drive exists, the path is writable, and the path does not point to a folder.

## CLI

```text
python -m chaintrace demo   [--db PATH] [--out DIR]      # synthetic case: import → analyse → notes → export → verify
python -m chaintrace export --db PATH --case ID [--out DIR]
python -m chaintrace verify REPORT.json --db PATH --case ID
```

`verify` recomputes the dataset fingerprint, re-runs the heuristics with the recorded parameters,
confirms the indicator IDs match, checks that every evidence reference resolves, and detects edits to the report file.

## Input CSV format

Required columns: `tx_hash, block_number, timestamp, from_address, to_address, asset, amount, data_source`.
Optional: `transfer_index` (default `0`; use it when one transaction contains several transfers).

* Addresses: `0x` + 40 hex. Hashes: `0x` + 64 hex (lower-cased on import; patterns are configurable via `ValidationConfig`).
* `timestamp`: ISO 8601; values without a timezone are treated as UTC.
* `amount`: non-negative decimal in the asset's display units. The original text is preserved as `amount_raw`.
* Each transfer is cited as `evidence_ref = <tx_hash>#<transfer_index>`.

## Heuristics (defaults)

| Heuristic | Fires when | Main parameters |
|---|---|---|
| `transaction_burst` | ≥ 8 transfers from (or to) one address within 10 min and ≥ 4 distinct counterparties | `burst_min_transfers`, `burst_window_minutes`, `burst_min_counterparties` |
| `unusual_value_change` | a transfer ≥ 10× the median of the sender's previous ≤ 20 same-asset transfers (needs ≥ 5) | `spike_factor`, `spike_min_history`, `spike_lookback` |
| `rapid_multihop` | ≥ 4 consecutive same-asset transfers, each starting ≤ 30 min after the last and forwarding 70–100 % of the value, no address revisited | `multihop_*` |
| `repeated_interaction` | ≥ 5 transfers between a **watchlist** address and one counterparty | `repeat_min_interactions` |

Priority (`high/medium/low`) is a *review order*, not a risk or guilt score. Each indicator carries an
explanation of why it fired, caveats naming benign explanations, parameters, metrics, and supporting evidence refs.

## Project layout

```text
src/chaintrace/
  schema.py  importer.py  adapters/      # canonical schema, validation, CSV + optional provider
  graph.py   timeline.py  viz.py         # filters, NetworkX graph, chronological view, Plotly
  heuristics.py  findings.py             # detectors, Indicator/Fact models
  cases.py   report.py   service.py      # SQLite store, report builder/verifier, orchestration
  synthetic.py  sample_data/             # deterministic synthetic dataset + manifest of planted patterns
  app.py (Streamlit)  cli.py
tests/        # 127 tests
docs/         # ARCHITECTURE, SAMPLE_INVESTIGATION, LIMITATIONS, DEMO_WALKTHROUGH
```

## Optional public-data adapter

`BlockscoutStyleAdapter` fetches an address's first page of native-coin transactions from a
Blockscout-style explorer (`/api/v2/addresses/{hash}/transactions`) using HTTPS GET only, no key. In the UI it sits
behind an opt-in checkbox. It is covered by tests against mocked responses and was **not verified against a live
endpoint** when written: check its output against the explorer before relying on it. Token transfers and pagination
are not implemented.

## Documentation

* [Architecture](docs/ARCHITECTURE.md) · [Sample investigation](docs/SAMPLE_INVESTIGATION.md) ·
  [Demo walkthrough](docs/DEMO_WALKTHROUGH.md) · [Limitations](docs/LIMITATIONS.md)
