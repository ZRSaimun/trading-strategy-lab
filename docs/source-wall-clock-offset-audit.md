# Declared source wall-clock offset comparison (offline, read-only)

`app.source_wall_clock_offset_audit.audit_declared_clock_offsets` compares **caller-provided source wall-clock minute labels** against an **independently supplied, sorted unique UTC minute inventory** for up to 32 explicit fixed-offset hypotheses. It does not read files, call a vendor, authenticate a calendar, choose a timezone, alter stored candles, or change trading eligibility. This is intended to investigate historical clock convention disagreements *before* UTC conversion and cross-worker M15 population comparison.

## Input convention

`source_wall_minutes` is an original source-order list of integer minute labels obtained by interpreting the **naive wall-clock fields as though UTC** (not an assertion that the source actually uses UTC). `anchor_utc_minutes` is an independently assembled, strictly increasing unique UTC M1 list. `offset_candidates_minutes` uses **local minus UTC**: for fixed EST (UTC−05:00), pass `-300`, and the hypothesis computes `UTC = naive_wall_label - (-300 minutes)`. This is a candidate comparison, **not** an automatic conversion or DST resolution. The caller must document the wall-field parser, offset convention, independent UTC anchor provenance, timestamp close/open convention, source ZIP identity and rights separately.

```python
from app.source_wall_clock_offset_audit import audit_declared_clock_offsets

# Synthetic data, not real market observations or a verified clock.
wall = [1_790_000_100 + 60*i for i in range(4)]
anchor = [minute + 300*60 for minute in wall]
result = audit_declared_clock_offsets(
    wall, anchor, source_id="synthetic:fixed-est",
    offset_candidates_minutes=[-300, -240, 0],
)
assert result["candidate_results"][0]["matched_distinct_anchor_minutes"] == 4
assert result["clock_offset_selected"] is False
assert result["research_ready"] is False
```

The report includes per-candidate matched distinct UTC anchor minutes, missing anchor minutes, shifted source minutes outside the anchor, integer anchor-overlap basis points, and a domain-separated SHA-256 of the matched minute set. It also reports source repeated-row count and backward jumps; repeated source rows cannot inflate overlap. The highest-overlap candidate count explicitly exposes ties, but **even a unique perfect overlap does not authenticate an offset**: market minute sequences can overlap under multiple wrong offsets. Every output keeps `clock_offset_selected=False`, `clock_offset_verified=False`, `dst_transition_verified=False`, `research_ready=False`, `live=False` and `may_execute_order=False`.

Input lists are nonempty and capped at 100,000 minute labels each. Candidate offsets are explicit, distinct, 15-minute multiples in [-840, +840], maximum 32. Source labels may repeat or jump backward; anchors must be sorted unique. Non-integer/bool values, unaligned minute labels, invalid identifiers, out-of-range shifts, empty lists and excessive inputs fail closed. No original prices, source archive bytes or credentials are included in the report.

**Research caveats:** HistData's published Generic ASCII M1 specification describes fixed EST without DST and BID OHLC, but uploaded archives and any independent anchor still need their own verification. This audit does **not** infer that a duplicated late-October hour is a DST event, infer trading sessions from missing minutes, validate executable ASK/spread, or establish data redistribution rights. It cannot resolve a source that actually uses DST-local timestamps: use independently documented clock and calendar evidence, and quarantine ambiguous wall times.

For the already-reproduced 11 historical archives (660 repeated M1 rows, 44 additional source-order complete M15 windows), first freeze private source-order minute inventories and original ZIP SHA-256s. Run fixed-offset comparisons against separately sourced UTC anchors, inspect candidate ties, and only then compare exact UTC bucket identities and Loop 2's 34-bar causal/full-horizon structural denominators. Do not treat a matching hash or timestamp overlap as independent price provenance or permission to backtest.

Synthetic regression tests (no API calls):

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_source_wall_clock_offset_audit.py
```

Official reference: [HistData file specification](https://www.histdata.com/f-a-q/data-files-detailed-specification/). The Trading 212 public API supports Invest and Stocks ISA accounts, not CFDs: [official API](https://docs.trading212.com/api). Twelve Data instrument coverage and permitted use are subscription/entitlement-dependent: [provider overview](https://support.twelvedata.com/en/articles/5609168-introduction-to-twelve-data).
