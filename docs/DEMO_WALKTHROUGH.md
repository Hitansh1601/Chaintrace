# Demo walkthrough (about 10 minutes)

1. **Start.** `streamlit run src\chaintrace\app.py`. In the sidebar, *Create case* (name, your name as investigator).
2. **Load data.** Click *Load synthetic demo dataset* (201 transfers). To try validation, upload a CSV with a bad row: the sidebar lists rejected rows with line numbers and reasons before anything is imported.
3. **Overview.** Read the dataset fact; pick an address profile (a statement about the loaded data only).
4. **Indicators.** Open *Heuristic parameters* (change one and see the effect), add `SYN-WATCH-W` to the watchlist, click *Run analysis*. Open each expander: why it fired, caveats, metrics, supporting transfers.
5. **Graph.** Search `FANOUT`, choose `SYN-FANOUT-SRC`, depth 2, direction `out`. Amber nodes appear in an indicator. Try the asset, time and amount filters; hover edges for totals.
6. **Timeline.** Select `SYN-CHAIN-H2`: chronological transfers with block, hash, sender, recipient, amount and the tagging indicator IDs.
7. **Notes.** Add an *observation* citing evidence from an indicator, then a *hypothesis* (low confidence). Try citing a made-up ref: it is refused.
8. **Export.** *Build report*, download HTML/JSON/CSV. Open the HTML: disclaimers, three evidence classes, appendix.
9. **Verify.** Save the JSON and run `python -m chaintrace verify report.json --db chaintrace_cases.db --case 1`. Edit one amount in the JSON and re-run: it fails.
10. **Headless.** `python -m chaintrace demo --out out\demo` reproduces a complete case with the same indicator IDs every time.
