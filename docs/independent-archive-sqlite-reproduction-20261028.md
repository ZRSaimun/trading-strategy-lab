# Independent original M1 archive → SQLite population reproduction (28 Oct 2026)

**Scope:** Owner-provided, private original HistData ASCII ZIP files and the separate research-only `trading_research_data_2026-10-25.zip` bundle. A disconnected read-only audit independently re-parsed each original CSV in source row order and queried the extracted `research.sqlite` using `mode=ro&immutable=1` / `query_only=ON`. No prices, archives, database bytes, credentials, or broker account information are committed.

**Snapshot identities:** compressed research bundle SHA-256 `cede27cabdbf29829faae95feb1e9ffb2ca4dcd77904e976d61168573882e912`; extracted SQLite SHA-256 `4348aeda6c2e32fd27d5b370b6c0cb782869a5649aeb847921d7a1004cf41652`. Every original ZIP SHA-256 matched the corresponding `historical_datasets.archive_sha256` field; this verifies *internal identity consistency*, not the publisher's identity or a license.

## Reproduced structural census

| Instrument / year | Original M1 rows | Stored admitted | Quarantined | Original source-order complete M15 | Stored complete M15 | Difference |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| NSXUSD 2021 | 343,006 | 342,946 | 60 | 22,852 | 22,848 | +4 |
| NSXUSD 2022 | 342,771 | 342,711 | 60 | 22,818 | 22,814 | +4 |
| NSXUSD 2023 | 299,349 | 299,289 | 60 | 19,929 | 19,925 | +4 |
| NSXUSD 2024 | 340,986 | 340,926 | 60 | 22,602 | 22,598 | +4 |
| NSXUSD 2025 | 340,553 | 340,493 | 60 | 22,588 | 22,584 | +4 |
| WTIUSD 2022 | 354,224 | 354,164 | 60 | 23,425 | 23,421 | +4 |
| WTIUSD 2023 | 280,046 | 279,986 | 60 | 17,371 | 17,367 | +4 |
| XAUUSD 2022 | 354,628 | 354,568 | 60 | 23,584 | 23,580 | +4 |
| XAUUSD 2023 | 308,812 | 308,752 | 60 | 20,440 | 20,436 | +4 |
| XAUUSD 2024 | 355,652 | 355,592 | 60 | 23,661 | 23,657 | +4 |
| XAUUSD 2025 | 354,011 | 353,951 | 60 | 23,564 | 23,560 | +4 |
| **Total** | **3,674,038** | **3,673,378** | **660** | **242,834** | **242,790** | **+44** |

All **660** repeated source minute rows had byte-identical OHLC *text* to the first occurrence of their minute, with **zero conflicting OHLC repeats** and **one backward timestamp jump per archive**. Each repeated block was 60 consecutive rows. Under the dataset's *declared* fixed UTC−05:00 interpretation, the four repeated M15 buckets per archive are 00:00, 00:15, 00:30, and 00:45 UTC on the Monday after the late-October clock-change weekend (2021-11-01, 2022-10-31, 2023-10-30, 2024-10-28, 2025-10-27). This correlation suggests a possible clock-change-related data duplication but **does not prove why the files contain repeats**. [HistData's official file specification](https://www.histdata.com/f-a-q/data-files-detailed-specification/) documents Generic ASCII M1 timestamps in **fixed Eastern Standard Time without DST adjustment** and labels OHLC as **BID** quotes. The declared UTC−05:00 conversion therefore matches the *published format convention*, but the individual uploaded ZIPs have no independently authenticated vendor signature, clock attestation or executable ASK quotes.

For every admitted source row, the original CSV **line number**, CSV **member name**, declared-offset UTC **timestamp**, and the **binary FLOAT conversion of all four OHLC values** matched the frozen SQLite row: **zero discrepancies** across 3,673,378 admitted records. This is not exact original-decimal preservation: SQLite stores binary FLOAT, so do not equate float-round-trip parity with original Decimal parity. No independent verification of original market prices was performed.

## Reproduction and release boundary

The independent scan streamed each ZIP CSV without extracting it; SHA-256 of each original compressed ZIP was checked against the research snapshot's manifest, and the stored rows were accessed only through a read-only SQLite connection. A complete M15 window means 15 source-order consecutive one-minute epochs beginning on a UTC quarter-hour. Replayed complete windows count twice; the stored comparison uses sorted unique accepted minutes. These are **structural window counts**, not validated market sessions, strategy signals or profitable trades.

The related [Loop 2 original-archive/SQLite row-parity CLI (draft PR #136)](https://github.com/ZRSaimun/trading-strategy-lab/pull/136) can provide a separate code-path reproduction when run with the original archives and dataset IDs. The independently performed audit here was a one-off isolated script; it did **not** execute that PR's CLI or the repository CI. Preserve the original ZIPs and frozen SQLite snapshot privately for repeatable forensic verification.

**Disposition: QUARANTINE remains required.** Do not silently collapse raw-source M15 samples into stored M15, backfill synthetic prices, release historical strategy eligibility, claim source freshness, or merge/deploy production changes from these counts. Verify the actual HistData timestamp convention (including DST), original licensing/usage rights, independent market calendar and expected bar inventory, source authenticity and quote side, and a documented duplicate-row/aggregation policy before authorizing research. This analysis never establishes live data, executable spreads, broker fills or permission for real-money orders.
