# Which blockchain does ChainTrace use?

Short answer: **no single hard-coded chain. ChainTrace is EVM-account-model,
chain-agnostic and read-only.** It analyses transfer tables; the chain is
whatever the rows came from. The presets in `src/chaintrace/chain.py`
(`SUPPORTED_CHAINS`) name the networks the format fits.

## 1. The format = EVM account model

Every row is one transfer: `from_address → to_address` with

* addresses `0x` + 40 hex (`ValidationConfig.address_regex`, `schema.py`),
* transaction hashes `0x` + 64 hex,
* `block_number`, ISO-8601 `timestamp`, `asset`, `amount` (display units),
  `data_source`, optional `transfer_index`.

That is Ethereum's account model. It equally fits Polygon, BNB Smart Chain,
Arbitrum, Base, Sepolia and any private EVM/Blockscout instance — they all
use the same address/hash encoding. It does **not** natively model UTXO
chains (Bitcoin), internal traces, or event-decoded token flows unless you
flatten them to one row per transfer first.

Checks are format-only (regex). There is no EIP-55 checksum validation, no
chain-id field on rows, no entity/sanction labelling — deliberately, to avoid
false attribution. `asset` is a display label (`ETH`, `USDC`, …); base-unit
conversion for live pulls uses `chain.decimals_for_asset` (18 for ETH-like,
6 for USDC/USDT, overridable).

## 2. Where do rows come from?

| Path | Chain | Module |
|---|---|---|
| Bundled synthetic CSV (`SYNTHETIC_DEMO_v1`, 201 rows, 61 addresses, 30 days) | **Simulated Ethereum mainnet**: chain id 1, ~12 s blocks from ~19 000 000, `ETH`/`USDC` | `synthetic.py` (`CHAIN_ID=1`, `BLOCK_TIME_SECS=12`, `SOURCE`), `chain.SYNTHETIC_CHAIN` |
| Your own CSV export | Any EVM chain you choose — record it in `data_source` | `adapters/csv_adapter.py` → `importer.validate_frame` |
| Optional live pull | Any **Blockscout v2** explorer: `ethereum` (1), `sepolia` (11155111), `polygon` (137), `bsc` (56), `arbitrum` (42161), `base` (8453), or custom URL | `adapters/provider_adapter.py` (`BlockscoutStyleAdapter`) |

The live adapter does HTTPS `GET` only to
`/api/v2/addresses/{hash}/transactions`, sends no key/credentials, maps
native-coin transfers, converts `value` (base units) with the asset's
decimals, and optionally follows `next_page_params` (`max_pages=1..10`,
default 1 = first page only). The `data_source` it writes records the
explorer host **and** the chain label, e.g.
`provider:eth.blockscout.com [ethereum] (public explorer API, read-only)`.

## 3. How to answer "which blockchain?" in a viva

> "ChainTrace doesn't run its own chain or node. It's an off-chain,
> read-only forensics helper for EVM-compatible chains. The demo dataset
> simulates Ethereum mainnet — chain id 1, 12-second blocks — so the
> heuristics run on realistic timing and denominations. For real data you
> either import a CSV exported from any EVM chain, or point the optional
> Blockscout adapter at that chain's explorer — Ethereum, Sepolia for free
> testnet data, Polygon, BSC, Arbitrum, Base. Everything downstream —
> graph, timeline, heuristics, evidence report — is chain-agnostic because
> it only sees the normalised transfer table."

## 4. What is *not* blockchain-specific (by design)

* No node/RPC client (`web3.py`, `eth-*` are not dependencies).
* No transaction construction, signing, broadcasting, or private keys
  (asserted by `test_adapters_declare_read_only_and_expose_no_write_api`).
* No consensus, gas, mempool, or contract-execution semantics.
* Amounts are analysed as floats (raw text preserved); fees/balances are
  ignored by the multi-hop rule — see `docs/LIMITATIONS.md`.

## 5. Good demo chains for a professor

* **Offline (always works):** the synthetic Ethereum-like dataset —
  `python -m chaintrace demo --out out\demo`.
* **Online (one address, 2 minutes):** Sepolia testnet via a public
  Blockscout instance — free, no key, clearly "real chain data" without
  touching mainnet funds. Verify the explorer page matches the import
  preview before relying on it (the adapter is mock-tested, not
  live-verified).
