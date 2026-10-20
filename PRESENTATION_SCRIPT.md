# ChainTrace — Presentation Script (for professor / viva)

Use this as your spoken script. Times are for a ~7-minute demo + questions.
All commands assume the repo root. Anything marked SAY is what you say;
anything in code blocks is what you type/show.

---

## 0. One-line pitch (SAY, 20s)

> "ChainTrace is a read-only blockchain forensics helper. You give it
> transfer data, it maps address-to-address flows, flags suspicious-looking
> patterns with transparent rules, and exports an evidence report where every
> claim links back to the exact transactions behind it. It never moves funds,
> never signs, never asks for private keys — and the bundled data is 100%
> synthetic, so it's safe to demo."

## 1. What it does, end to end (SAY, 60s + live UI)

Show the Streamlit UI (or the `out\demo` folder if offline):

1. **Import** — CSV with strict validation. Bad rows are never silently
   dropped: you get line numbers + reasons, plus a SHA-256 of the import.
2. **Cases** — SQLite case file: imports, notes, hypotheses with
   status/confidence, watchlist, analysis runs.
3. **Graph** — directed NetworkX/Plotly graph: filter by time, asset,
   amount, hop depth/direction from a seed address.
4. **Timeline** — chronological table of every transfer with evidence refs
   and indicator tags.
5. **Heuristics** — 4 transparent detectors (below). Each indicator shows
   its rule, thresholds, metrics, caveats, and supporting transfers.
6. **Evidence model** — observed facts vs derived indicators vs your
   hypotheses, kept in separate report sections.
7. **Export + verify** — JSON, CSV, self-contained HTML; `verify`
   re-derives the report and catches edits.

Live commands (headless, no UI needed):

```powershell
python -m pytest -q
python -m chaintrace demo --out out\demo
python -m chaintrace verify out\demo\report.json --db <db> --case <id>
```

`demo` does import → analyse → notes → export → verify in one go.

## 2. Which blockchain, and how? (SAY — this is the question they WILL ask, 90s)

> "ChainTrace doesn't run its own blockchain and doesn't connect to a node.
> It's off-chain analytics for EVM-compatible chains. Every row is one
> account-model transfer — 0x address to 0x address — which is Ethereum's
> format, and equally Polygon's, BNB Chain's, Arbitrum's, Base's, Sepolia's.
> The demo data simulates Ethereum mainnet: chain id 1, 12-second blocks
> from block 19 million, ETH with 18 decimals and USDC with 6. For real data
> you either import a CSV from any EVM chain, or use the optional Blockscout
> adapter — HTTPS GET only, no API key — pointed at that chain's explorer.
> Everything downstream is chain-agnostic because it only sees the
> normalised transfer table."

Point to proof in code (open these files):

* `src/chaintrace/chain.py` — `SUPPORTED_CHAINS` (ethereum 1, sepolia
  11155111, polygon 137, bsc 56, arbitrum 42161, base 8453), `ASSET_DECIMALS`,
  `SYNTHETIC_CHAIN`. **New in this build** — previously the chain was implicit.
* `src/chaintrace/synthetic.py` — `CHAIN_ID = 1`, `BLOCK_TIME_SECS = 12`,
  `SOURCE = SYNTHETIC_DEMO_v1`.
* `src/chaintrace/adapters/provider_adapter.py` —
  `BlockscoutStyleAdapter(base_url, address, chain="ethereum", max_pages=1)`:
  GETs `/api/v2/addresses/{hash}/transactions`, converts base units with
  per-asset decimals, records `provider:{host} [{chain}]` in `data_source`.
* `src/chaintrace/schema.py` — `ValidationConfig` (address `0x`+40 hex,
  hash `0x`+64 hex). Format check only, no checksum, no attribution.
* `docs/BLOCKCHAIN.md` — the one-page chain answer.

What it is NOT (say this before they ask — it builds trust):

* No Bitcoin/UTXO, no internal traces, no decoded ERC-20 events unless you
  flatten them to rows; no gas/mempool/consensus; no signing/broadcasting
  (there is a test asserting no `send/sign/broadcast/private_key` API exists).

## 3. The 4 heuristics (SAY, 60s — show Indicators tab)

| Heuristic | Fires when (defaults) |
|---|---|
| `transaction_burst` | ≥ 8 transfers from/to one address in 10 min, ≥ 4 distinct counterparties |
| `unusual_value_change` | transfer ≥ 10× median of sender's last ≤ 20 same-asset transfers (needs ≥ 5) |
| `rapid_multihop` | ≥ 4 same-asset hops, each ≤ 30 min apart, forwarding 70–100%, no revisit |
| `repeated_interaction` | ≥ 5 transfers between a **watchlist** address and one counterparty |

Key line: "Priority is review order, not a risk score. Every indicator
lists benign explanations — the demo deliberately includes a payroll-like
burst that trips the rule, to show a false positive handled honestly."

The synthetic manifest (`sample_data/synthetic_manifest.json`) plants 5
patterns: fan-out burst, 38-ETH spike, 6-hop chain, 9× watchlist repeat, and
the benign payroll burst. All 5 are found; the 140 background transfers
produce nothing.

## 4. Why the evidence model matters (SAY, 30s — show report.html)

Open `out\demo\report.html`: facts, indicators, your observations/hypotheses,
then an evidence appendix where every `evidence_ref = txhash#index` resolves.
`verify` recomputes the dataset fingerprint, re-runs heuristics with recorded
parameters, checks indicator IDs and references, and detects file edits.
Reports prove *internal consistency*, not that the source data is authentic —
say that line; professors love it.

## 5. Is this a good cybersecurity/blockchain project? (SAY if asked, or use as Q&A)

Honest framing — use this, don't oversell:

**Strong as a security-forensics project:**
* Correct threat model: read-only, no keys, explicit disclaimers, no
  identity attribution ("graph proximity is not proof").
* Reproducibility is real: deterministic IDs, SHA-256 fingerprints,
  staleness guard, `verify` command. Most student tools skip this.
* Validation honesty: rejects with reasons, SQL-bound, HTML-escaped,
  CSV-formula-neutralised.
* 128 tests covering heuristics, importer, cases, graph, report, provider
  (mocked), end-to-end demo.

**Weak as a "we built a blockchain" project — so don't frame it that way:**
* It doesn't implement a ledger, consensus, P2P, wallets, or smart contracts.
* Live chain support is thin: first-page native transfers, mock-tested,
  unverified against a live endpoint; no pagination beyond `max_pages`,
  no token/internal flows.
* Frame it as *"blockchain security analytics / forensics tooling"* —
  like Chainalysis/Etherscan-investigation workflows — not a protocol.

**What was improved in this build (so you can claim contribution):**
1. `chain.py` — explicit multi-chain registry (6 EVM presets + decimals +
   Sepolia-for-demos guidance). Before, the chain was folklore.
2. `BlockscoutStyleAdapter` — `chain` label recorded in `data_source`,
   per-asset decimals (USDC 6 vs ETH 18), opt-in `max_pages` pagination
   with dedupe, `pages_fetched`/`skipped` accounting. Defaults unchanged
   so all 128 existing tests still apply.
3. Synthetic data now declares `CHAIN_ID`/`BLOCK_TIME_SECS`/`CHAIN_NOTE`.
4. README "Which blockchain?" section + `docs/BLOCKCHAIN.md`; test-count
   fix (127 → 128).
5. UI chain picker in the provider panel.

Suggested next steps (if they ask "what would you add?"):
Sepolia live-fetch demo with explorer cross-check; ERC-20 decoding via
`token_transfers` endpoint; EIP-55 checksum warning (needs keccak, not
stdlib sha3); case-level chain-id column; PDF-native export.

## 6. Live demo script (5 minutes, offline-safe)

1. `python -m chaintrace demo --out out\demo` → show `report.json`,
   `report.html`, `findings.csv`, `evidence_transactions.csv`.
2. Open Streamlit → Overview (dataset fact + import log) → Graph
   (seed `SYN-FANOUT-SRC`, depth 2, out) → Timeline → Indicators
   (open the multi-hop + the payroll false positive side by side) →
   Notes (observation vs low-confidence hypothesis) → Export.
3. `python -m chaintrace verify out\demo\report.json ...` → "verification passed".
4. (Optional, online) Fetch 50 transfers of a Sepolia address via the
   provider panel, show the import preview, and compare one row against the
   explorer in a browser.

## 7. Likely viva questions + 15-second answers

* *"Which blockchain does it use?"* → EVM-account-model, chain-agnostic;
  demo simulates Ethereum mainnet (id 1); live via any Blockscout v2 chain.
* *"Does it transact?"* → No. GET-only provider, no signing API (tested).
  Read-only by construction.
* *"Can it identify criminals?"* → No. Leads, not verdicts. No attribution;
  proximity ≠ ownership. Needs off-chain evidence.
* *"What if data is missing?"* → Facts describe only the loaded set;
  missing transfers change every statistic. Staleness guard blocks export
  after data changes.
* *"False positives?"* → Yes, by design shown: payroll burst. That's why
  caveats + confidence + verify exist.
* *"Why SQLite?"* → Single-analyst case file, portable, no server. Not a
  multi-user evidence system (no auth/audit log) — stated in Limitations.
* *"Why not Bitcoin?"* → UTXO needs input/output modelling; currently one
  row = one sender→recipient. Convertible by preprocessing, not native.

---

*Generated for ChainTrace. Demo data is synthetic (`SYNTHETIC_DEMO_v1`);
no real wallets, people, or funds are involved.*
