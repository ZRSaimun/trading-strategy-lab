# Evidence-driven trading hypotheses: higher timeframes, CFD costs and New York close research

**Status: Research only.** No new broker endpoints, orders, live alerts, production mutations, cloud archive import or confirmed profitable trading strategy.

This protocol records proposed strategies as **hypotheses to test**, not market facts. The owner's requested numerical filters (40% CRT wick threshold; 1.5× 20-bar median range; 1.5× 20-bar *valid exchange/tick* volume; 50% FVG midpoint rejection; 0.5–1% position risk; 15-minute high-impact news block) are suggested *parameter candidates*, not established, universally successful thresholds.

## Immediate implemented experiment: NY close momentum

In the private terminal, **NY Close Research** loads **one source-isolated READY archive** via the existing authenticated, paginated `1m` candle API. The read-only module `frontend/lib/ny-close-momentum.ts`:

- Requires positive, finite, ordered, exactly one-minute complete BID OHLC, SHA-256 archive identity and an owner-entered nonzero hypothetical round-trip cost.
- Uses the **America/New_York** civil clock (including daylight-saving changes) and requires **all 390 historical 1-minute bars** for each 09:30–16:00 NY equity regular session. Partial sessions, early closes and gaps are excluded instead of filled. There is no official exchange-session calendar yet: unexpected full-day omissions cannot be distinguished from actual closures.
- Defines prior-session reference close as the previous complete session's 15:59 one-minute close.
- First-half-hour direction = 09:59 bar close versus 09:30 bar open.
- Day-to-15:30 direction = 15:30 bar **open** versus previous session's 15:59 close; the 15:30 open is eligible only after earlier completed bar data. Require both directions to be nonzero and agree.
- Volatility gate = first-half-hour high–low price range / 09:30 open, strictly **greater** than the median of the preceding **20 complete sessions**. Current/future sessions never contribute to their own threshold.
- Entry *assumption* = 15:30 NY open and exit *assumption* = 15:59 close (16:00 boundary), one hypothetical position per accepted session. This is an exploratory 30-minute hold, **not one-minute scalping**.
- Recalculates illustrative mean net basis points, win rate and gross-profit-to-loss profit factor at 0×, 1×, 2× and 3× the user's cost scenario. Reports the ungated same-direction comparator as a useful negative control.
- Never estimates absent executable ask, intraminute slippage, financing, marginal borrowing, commissions, funding, actual broker contract values, dividends or intraday equity risk.
- Reads up to **100,000 recent raw one-minute archive bars** in bounded authenticated pages and retains at most **20,000 US equity regular-session minutes**. A partial first/last session is excluded. This is still a **limited historical window**, not a seven-year or complete-archive backtest, and reading raw CFD history does not establish that an instrument follows US equity session conventions.

The original academic effect is **not a verified CFD edge**. Gao, Han, Li and Zhou (2018), *Market intraday momentum*, Journal of Financial Economics 129(2), pp.394–414, DOI https://doi.org/10.1016/j.jfineco.2018.05.009 studied SPY (1993–2013) and other ETFs. Rosa (2022), *Understanding intraday momentum strategies*, Journal of Futures Markets, DOI https://doi.org/10.1002/fut.22375, reports that a related strategy's out-of-sample predictability disappeared. These results cannot be transferred to NSXUSD/NDX cash proxies, futures, XAUUSD or WTI without source-specific testing and defensible markets/sessions.

## Remaining gated ICT/CRT experiments (NOT silently activated)

1. **Default primary research on 1H/4H**. Retain minute bars for fine event-time/price-quality measurement; do not treat 1m/5m/15m FVG detection as a profitable strategy. For 4H CRT, use exact closed Candle 1 range; candidate manipulation depth = outside-wick excursion divided by Candle 1 full range, and investigate 40% as a *configurable rejection hypothesis*.
2. **Higher-timeframe alignment.** Formally define a 4H supply/demand zone and daily trend using past data only; refuse an unsupported order-block claim until rules and candle session/calendar are reproducible. Prevent confirmation signals from using the as-yet-unclosed higher-timeframe candle.
3. **15-minute displacement/structure shift and FVG midpoint rejection.** Define local pivot causally, require completed-bar confirmation, compare directional candle range against prior 20-bar *median* with a candidate 1.5× threshold, and for midpoint rejection compare wick length/whole candle range. Do not hard-code a claimed 3–6% win-rate lift or use the outcome candle in signal selection.
4. **Volume gates** must require a verified volume classification. HistData M1's zero placeholders are **not proof of actual exchange volume**. A 1.5× volume gate is `INSUFFICIENT_DATA` without classified volume and prior 20-bar history, not `passed` and not implied from price movements.
5. **Macro and options/VIX** experiments require licensed timestamped VIX/sentiment/economic-calendar feeds, *first-published* revision-aware releases, and causally aligned timestamps. Not implemented. The user's VIX, CPI, FOMC and FVG percentages/Sharpe figures are **not assumed transferable** or verified in this repository.

## CFD cost and risk safeguards (planned, existing previews retained)

- Broker-specific instrument and contract mapping, margin schedule, tick/point value, rollover, currency conversion, and actual **BID/ASK** recordings for at least a forward demo observation period before attributing any simulated profit.
- Illustrative round-trip penalties such as 1.8, 2.0 or 3.5 basis points **are not observed broker spreads**. Stress varying spread, slippage, financing, spread spikes and gap stops; require actual contract sizing. Do not transform bid-only candles into fictitious observed asks.
- Overnight funding cutoff is **provider-, instrument- and DST-specific**, not universally 17:00 New York. Example: IG UK lists 22:00 UK cutoff for daily-funded cash CFD positions; verify with the exact broker before programming session flattening: https://www.ig.com/uk/help-and-support/articles/681712-what-is-overnight-funding-how-is-it-charged-and-how-is-it-calculated
- Risk policies such as 0.5% maximum per candidate, account daily drawdown stop, and 15-min pre-news halt/exit are prospective **controls**, not quantified proven alpha. Real stops, outages, spikes and margin liquidations can lose more than the nominal bound. External verified timestamped calendar and authenticated source required before automated blocking.
- Profit factor above 1.15 or a Deflated Sharpe Ratio probability above 0.95, if chosen, are **screening criteria** only. The deflated Sharpe requires multiple-trial, sample-distribution and nonnormality modelling, *not* a simple sample Sharpe threshold. Not computed by this module. Multiple-testing correction and genuinely held-out forward results remain pending.

The repo's confluence/CRT research in PR #24 is independent; do not misrepresent this NY session experiment as an implementation of its 4H/15m pattern conditions.

### Tests

`frontend/tests/ny-close-momentum.test.ts` and `frontend/tests/ny-close-history.test.ts` check 20-session trailing cutoff, 390-minute completeness, DST-aware NYC boundaries, no lookahead on 15:30 entry decisions, neutral/rejected outcomes, and strictly validated source/cost inputs. Run the frontend test/build jobs in GitHub Actions. A synthetic regression pass does not demonstrate live or historical profitability on the owner's private archive.
