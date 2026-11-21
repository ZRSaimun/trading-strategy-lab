# Hourly FVG: prevent future-driven volume verification promotion

The causal 1H FVG scanner must not allow a future candle timestamp accessor to change the declared volume source from `unverified` / `volumeVerified: false` to `exchange` / `volumeVerified: true`. The synthetic regression in `frontend/tests/hourly-fvg-future-volume-verification-promotion.test.ts` asserts immediate source-declaration rejection before a second future timestamp or any future OHLC, volume, or minute-coverage read.

This is an integrity regression for the *declared* prior-20 volume gate. It does not authenticate exchange volume, supply a source receipt, or prove a profitable wick rejection. A caller's truthful volume declaration still requires independent source identity and authorization checks. The study remains BID-only, paper-only and not a broker execution model.
