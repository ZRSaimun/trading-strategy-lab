# Offline source data-quality review

Run in an authorised environment against the private SQLite database created by `app.bulk_import`. This tool **never sends data anywhere, writes to the source DB, requests market feeds, or performs trades**.

```bash
cd backend
python -m app.data_quality_research /private/path/research_real.sqlite --output /private/path/audit.json
PYTHONPATH=. pytest -q tests/test_data_quality_research.py
```

The report contains:

- A per-archive manifest with source identity, SHA-256 hash, declared fixed clock offset, accepted and rejected rows (suitable for independently checking source data when made available).
- Accepted source counts versus actual stored rows, with discrepancies highlighted.
- Per-provider/instrument/file-format comparisons (never conflating cash indexes, futures and CFDs).
- Same-source, same-minute overlaps and conflicting OHLC values across imported archives.
- Year-level observed minute counts, numerical zero-volume counts and counts of observed inter-bar gaps.
- A count of invalid OHLC structures among accepted rows.

**Important limitations:** A time gap is merely an interval with no recorded bars, **not evidence of missing trading minutes** (sessions, weekends and holidays apply). Quote coverage cannot be estimated without an instrument-specific trading calendar. HistData OHLC is bid only, not bid/ask or executable spread data; recorded zero volume is not exchange volume. The importer already excluded malformed and backward-time rows; this audit cannot establish the truth of excluded prices or third-party licensing. A SHA-256 hash establishes byte identity, not authenticity.

The output JSON may include private archive filenames and hashes. **Do not commit real data or its detailed manifests to the public GitHub repository.** Store real reports in the private research workspace. The public repository contains only reproducible code and synthetic tests.

The audit is primarily for the independent Gemini research team and the project's backtesting data-quality gate; it does not change the live website or prove strategy profitability.