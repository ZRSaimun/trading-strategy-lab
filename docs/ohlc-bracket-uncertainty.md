# M1 bracket outcome uncertainty audit (offline, Loop 2)

**Scope:** `backend/app/ohlc_bracket_uncertainty.py` is a pure Python, non-executing historical sensitivity tool. It is **not** connected to a broker, production database, authenticated API, chart, strategy optimizer or live signal service.

## Frozen input and causal boundary

Each observation declares a unique `path_id`, exact `instrument/provider/venue`, archive SHA-256, historical `price_side` (BID/ASK/MID), LONG/SHORT, `signal_at` (UTC minute-aligned **completed signal close**), `entry_at=signal_at+60`, entry, stop, target, horizon in minutes (1–1440), and up to that many completed M1 OHLC candles. All prices are exact bounded decimal strings. The first M1 open must equal the declared entry; stop and target must strictly straddle entry. The strategy must freeze stop, target and horizon **before** viewing any outcome candles; this helper cannot prove that external preregistration occurred.

An M1 candle is indexed by its UTC minute-open timestamp. Only future candles beginning at the next minute after the completed signal can determine an outcome. Every supplied candle must have a valid OHLC envelope and increasing timestamp. The evaluator never interpolates absent candles or assumes an intra-minute high/low ordering.

## Outcome rules

- First unambiguous stop touch: exit at stop. First target touch: exit at target.
- Both stop and target touched within one M1 candle: `AMBIGUOUS`; return lower/upper R from **stop-first** versus **target-first**. Do not count as a definite winner.
- Adverse open gap through stop: use worse opening price; favorable open gap beyond target: cap at target. These are deliberately simple hypothetical assumptions, not executable fills.
- If no bracket is hit in the complete frozen horizon: mark the final observed M1 close as a hypothetical exit.
- Missing M1, a gap before exit, or incomplete horizon: `CENSORED` with **null** returns. It is neither flat nor a losing/winning observation. Invalid prices/identity/timing raise an error rather than being repaired.
- Cost grid is **additional** illustrative round-trip `0/5/10/20 bps` on absolute entry notional. Cost in R is `abs(entry) * bps / 10000 / abs(entry-stop)`. It is not a broker spread, CFD funding, tick-size, exchange fee, or live quote.
- Signed negative historical oil prices are allowed; a zero entry price is rejected. All arithmetic uses Python `Decimal`.

`audit_paths` requires a single exact source identity, a common frozen horizon, unique path IDs and unique completed-signal minute timestamps. It reports determinate, ambiguous and censored counts. It withholds **all population means** if *any* path is censored, if fewer than 30 paths exist, or if fewer than 12 distinct ISO UTC weeks are represented. Otherwise it reports **descriptive** mean lower/upper R for the fixed cost grid; these are not confidence intervals or statistical significance tests. The full historical signal population and archive timebase must be verified externally.

## Example (synthetic only)

```python
from app.ohlc_bracket_uncertainty import evaluate_path
path = {
    'path_id':'synthetic-1', 'instrument':'NSXUSD-CFD',
    'provider':'synthetic', 'venue':'synthetic', 'price_side':'BID',
    'archive_sha256':'a'*64, 'direction':'LONG',
    'signal_at':1760313600, 'entry_at':1760313660,
    'entry':'100', 'stop':'99', 'target':'102', 'horizon_minutes':1,
    'bars':[{'at':1760313660,'open':'100','high':'102',
             'low':'99','close':'100'}]
}
result = evaluate_path(path)
assert result['status'] == 'AMBIGUOUS'
assert result['lower_gross_r'] == '-1'
assert result['upper_gross_r'] == '2'
```

Run synthetic regression tests: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_ohlc_bracket_uncertainty.py`.

## Limits and handoff

The module does **not** establish archive authenticity, usage rights, correct HistData UTC/DST convention, spread, slippage, real order queue position, margin, stop execution, futures rolls, or profitable trading performance. A source checksum is an identity key, not an authenticity certificate. BID-only source bars cannot validate both sides of CFD execution.

For #24 confluence research, freeze the CRT/ICT entry, stop, target and outcome horizon using only completed prior candles; pass *every* eligible path including censored paths to this independent M1 evaluator. For #29, preserve frozen source identity, chronology and untouched holdout membership. For #41/#43, do not unlock quarantined historical archives on format parity alone. Never choose a strategy by retrospectively maximizing upper-bound outcomes. No real-money or paper order submission is implemented here.
