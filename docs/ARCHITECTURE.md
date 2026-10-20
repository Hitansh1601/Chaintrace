# Architecture

```text
 CSV / synthetic ──► CsvAdapter ───────┐
 public explorer ──► ProviderAdapter ──┤  (optional, off by default, HTTPS GET only)
                                       ▼
                 importer.validate_frame  → valid rows · rejected rows + reasons · SHA-256
                                       ▼
        CaseStore (SQLite): cases · imports · transactions · notes · watchlist · analysis_runs
                                       │ canonical DataFrame
      ┌──────────────┬─────────────────┼──────────────────┐
      ▼              ▼                 ▼                  ▼
   graph.py     timeline.py      heuristics.py       findings.py
                                       │                  │
                                       └──► Indicator ◄───┘ (Fact, Indicator)
                                       ▼
                  report.py: build_report · verify_report · JSON/CSV/HTML renderers
                                       ▼
                       service.py ◄── app.py (Streamlit) · cli.py
```

## Design decisions

* **One canonical table.** Every adapter ends in `validate_frame`, so heuristics, graph and reports never see unvalidated data.
* **Evidence references everywhere.** `tx_hash#transfer_index` is the primary key of every transfer. Indicators, facts and notes carry lists of these; the report builder refuses to emit a report with a dangling reference (`EvidenceReferenceError`) and notes are rejected at write time if they cite unknown transfers.
* **Three evidence classes.** Facts (computed from rows), indicators (heuristic leads with rule + caveats), hypotheses/observations (analyst text with status and confidence). They are separate sections in JSON, HTML and CSV (`kind` column).
* **Determinism.** Rows are sorted by `(timestamp, block, tx_hash, transfer_index)`; indicator IDs are SHA-1 digests of heuristic + addresses + evidence refs; the report ID is a hash of the report's content (excluding generation time and environment). Re-running on the same data and parameters yields the same IDs.
* **Staleness guard.** A saved analysis records the dataset fingerprint; exporting after the data changed raises `StaleAnalysisError`.
* **Read-only by construction.** No signing, key handling or write-capable provider calls exist. The provider adapter uses `GET` only and attaches no credentials.
* **Untrusted text.** HTML output is escaped; CSV cells starting with `= + - @` are neutralised; SQL uses bound parameters.

## SQLite schema (summary)

| Table | Key columns |
|---|---|
| `cases` | id, name, investigator, description, created_at |
| `imports` | id, case_id, source_name, sha256, valid_rows, rejected_rows, inserted_rows, imported_at |
| `transactions` | PK (case_id, evidence_ref); tx_hash, transfer_index, block_number, timestamp (ISO UTC), from/to_address, asset, amount, amount_raw, data_source |
| `notes` | id, case_id, kind (`observation`\|`hypothesis`), text, evidence_refs (JSON), author, confidence, status |
| `watchlist` | (case_id, address) |
| `analysis_runs` | case_id, run_at, dataset_sha256, config_json, watchlist_json, indicators_json |

## Report structure (JSON)

`report_id`, `tool`, `case`, `disclaimers`, `reproducibility` (dataset SHA-256, parameters, watchlist, import log),
`observed_facts`, `derived_indicators`, `investigator_observations`, `investigator_hypotheses`,
`evidence` (every cited transfer, with `referenced_by`), `generated_at_utc`, `environment`.
