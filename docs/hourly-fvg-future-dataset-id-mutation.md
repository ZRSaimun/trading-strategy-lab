# Future-triggered dataset identity mutation regression

The 1H FVG causal as-of study must keep the source `datasetId` fixed while discovering unrevealed candle timestamps. A synthetic future timestamp getter attempts to replace the completed-prefix dataset identifier. The regression requires immediate source-declaration integrity rejection before reading the second future timestamp or any unrevealed OHLC, volume, or observed-minute coverage field.

Test: `frontend/tests/hourly-fvg-future-dataset-id-mutation.test.ts`. This is a defensive test using deliberately synthetic candles and a caller-controlled declaration, not authentication of dataset identity, licensed market history, verified volume, broker BID/ASK execution, or trading profitability. Remain draft, paper-only, unmerged and undeployed; verify CI against the exact updated commit.
