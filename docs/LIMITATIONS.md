# Limitations

**Interpretation**
* Indicators are heuristics. They produce false positives (the demo includes one on purpose) and false negatives (structuring that stays under the thresholds, activity spread over time, mixers, cross-chain bridges).
* Observed facts describe the *loaded* dataset only. Missing transfers change every statistic and can hide or create patterns.
* Graph layout distance is meaningless; edges are observed transfers, nothing more. No clustering or ownership inference is attempted, deliberately.
* Priority is review order, not a risk score.

**Data scope**
* Account-model (EVM-style) transfers only: one sender, one recipient per row. UTXO chains (Bitcoin), internal transactions, event-decoded token flows, NFTs, and contract-level semantics are not modelled unless you convert them to rows yourself.
* Amounts are analysed as 64-bit floats (original text is preserved). Very large or high-precision values lose precision in sums and ratios.
* Timestamps are treated as UTC; sub-second precision is retained but block time and wall-clock time can differ.
* Address validation checks format, not EIP-55 checksums. There is no entity or sanction labelling; the synthetic role labels are fiction.

**Heuristics**
* Multi-hop detection ignores balances and fees; it caps branching (5) and chains (200) per asset to bound run time, and assumes a hop forwards ≤ the amount received.
* Value-change detection uses only the sender's history inside the loaded data and detects spikes, not drops.
* Repeated interaction is evaluated only for watchlist addresses.

**Provider adapter**
* Experimental. Mapping follows the documented Blockscout v2 shape and is tested only against mocked payloads; it has not been verified against a live endpoint. First page and native-coin transfers only; no pagination, token transfers, or retry/backoff. Public endpoints rate-limit.

**Tool**
* Single-user SQLite, no authentication or audit log of UI actions beyond timestamps on notes/imports. Not a substitute for forensic acquisition tooling or chain-of-custody procedures.
* The HTML report is the PDF path (browser print). No native PDF export.
* Reports prove internal consistency (fingerprint, IDs, references), not that the source data is authentic.
