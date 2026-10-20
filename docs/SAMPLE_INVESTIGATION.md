# Sample investigation (synthetic data only)

Everything below uses the bundled **synthetic** dataset (`SYNTHETIC_DEMO_v1`, 201 transfers, 61 invented
addresses, 30 days). The addresses are hashes of role labels like `SYN-FANOUT-SRC`. They are not real wallets,
and the role labels say nothing about any real person or entity. The patterns were planted on purpose and are
listed in `src/chaintrace/sample_data/synthetic_manifest.json`; this is a demonstration of the *workflow*,
not a real-world finding.

Reproduce it: `python -m chaintrace demo --out out\demo` (dataset SHA-256 `5789151298a9…`).

## Results

With default parameters and `SYN-WATCH-W` on the watchlist, ChainTrace produces five indicators. All five planted
patterns are found and the 140 background transfers produce none.

| ID | Heuristic | Priority | What the data shows (observed) |
|---|---|---|---|
| IND-AD7C6DBE6F | burst | medium | `SYN-FANOUT-SRC` sent 14 transfers (≈23.8 ETH) to 14 distinct addresses in 6 m 10 s, about 40 min after receiving 24 ETH from a single address |
| IND-4CDB323F0E | value change | high | 38 ETH from `SYN-SPIKE-ACCT`, 64× the median (0.59 ETH) of its 8 previous ETH transfers |
| IND-98AC67CB08 | multi-hop | high | 6 consecutive ETH forwards over 17 m 40 s, 20 ETH in and 18 ETH out of the last hop; small 0.1 ETH side payments leave the chain |
| IND-510863C787 | repeat | medium | `SYN-WATCH-W` and `SYN-CPTY-X`: 9 transfers (5 out, 4 in) over 8.1 days |
| IND-FD1094C8E7 | burst | medium | `SYN-PAYROLL` sent 10 USDC transfers (24,200 USDC) to 10 addresses in 5 m 15 s |

## How an analyst would work it

1. **Triage.** Sort by priority, open each indicator, read *why it fired* and the *caveats*.
2. **Check the benign explanation first.** IND-FD1094C8E7 (the payroll-like burst) matches a plausible batch payout: one sender, salary-like amounts, even spacing. It is a deliberate false positive showing that the burst rule alone cannot separate payouts from structuring. The demo records this as a *hypothesis with medium confidence*, not as a conclusion.
3. **Follow the flow.** In the Graph tab, seed `SYN-FANOUT-SRC`, depth 2, direction `out`. Five of the 14 recipients later forward ~1.69 ETH to one address (`SYN-CONSOLIDATOR`) after 2+ hours. That is observable and slower than the rapid-chain rule, so it is not flagged; it is a lead to examine.
4. **Record what you know vs. suspect.** The demo stores one observation (funding followed by fan-out, citing the first and last supporting transfers) and one low-confidence hypothesis (splitting to avoid per-address monitoring) *with the alternative* (ordinary batch payout) and a next step.
5. **Export and verify.** `report.html` shows each class in its own section with an evidence appendix; `python -m chaintrace verify` re-derives the checks.

## What this does not establish

Nothing here says who controls any address, why funds moved, or that any activity is unlawful. Real cases need
independent evidence (exchange records, legal process, off-chain context) before any attribution.
