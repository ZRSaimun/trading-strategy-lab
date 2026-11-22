# Future-triggered dataset identity mutation regression

The 1H FVG causal as-of study must keep the source `datasetId` fixed while discovering unrevealed candle timestamps. A synthetic future timestamp getter attempts to replace the completed-prefix dataset identifier. The regression requires immediate source-declaration integrity rejection before reading the second future timestamp or any unrevealed OHLC, volume, or observed-minute coverage field.

Test: `frontend/tests/hourly-fvg-future-dataset-id-mutation.test.ts`. This is a defensive test using deliberately synthetic candles and a caller-controlled declaration, not authentication of dataset identity, licensed market history, verified volume, broker BID/ASK execution, or trading profitability. Remain draft, paper-only, unmerged and undeployed; verify CI against the exact updated commit.

A paired non-mutating control now checks that a legitimate future timestamp can be inspected once while its unrevealed market fields remain untouched, the original dataset ID is preserved in the result, and exactly two completed bars are counted. This distinguishes fail-closed mutation detection from accidentally rejecting every future timestamp; it still does not authenticate the source.

A second positive control supplies **two** unrevealed timestamp getters and throws on every future OHLC, volume and coverage accessor. It requires each timestamp to be inspected exactly once, neither market payload to be read, the completed-prefix dataset identity to remain unchanged, and exactly two completed bars in the result. This catches accidental market-field reads while iterating over multiple future rows. Synthetic-only evidence; no strategy performance inference.

A third regression mutates the dataset identity only when the **second** unrevealed timestamp is inspected. It requires rejection before a third future timestamp or any unrevealed market field is accessed. This tests integrity checks throughout future-row iteration rather than only on its first row; it remains synthetic and does not establish genuine source provenance or profitable performance.

A fourth regression injects a throwing getter for the first unrevealed timestamp, followed by another future row. It requires propagation of the timestamp failure with exactly one failing timestamp read, no later timestamp read, no future market-payload access, and an unchanged completed-prefix dataset ID. This is a synthetic fail-closed accessor test, not evidence of a live source or strategy edge.
