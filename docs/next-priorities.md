# Remaining work and useful next milestones

Current public release is a browser-local research application plus separate provider-hosted chart displays. It is not the completed private, connected research terminal described in the master specification.

## 1. Reliable chart navigation

Keep exact feed identities visible; make restricted feeds explain themselves and expose explicit alternate choices. Preserve those choices on each device. Reproduce any remaining blank/null report using its exact symbol, device/browser, interval and visible error. Cross-origin frame load is not proof of candles. Provider entitlement cannot be repaired by renaming a CFD as an index or futures contract.

## 2. One verified private data workflow

Select an owner-controlled HTTPS backend host, preserving server-side keys and authentication. Verify a data source's exact Gold and Nasdaq instrument entitlements, history, limits, costs and permissions before activating it. Import authorized real candles, validate times/coverage/freshness, then verify chart → replay → backtest → saved report/journal → backup using that same dataset. Presently this acceptance workflow is not verified with real owner data. The disabled historical Gold adapter is not a live feed and does not cover Nasdaq. GitHub Pages only serves the static browser app.

## 3. Completed-candle automation

Only after the private ingestion workflow works: implement idempotent candle-close processing, freshness checks, restart recovery, state transitions, and notification delivery. Existing alerts run during historical replay in an open tab; they are not an unattended market monitor. Require deterministic no-lookahead tests and real feed event verification. News/calendar data needs an authorized source too.

## 4. Authenticated AI access

Scoped, expiring/revocable tokens, 13 schema-validated tools, audited/idempotent drawing writes and official MCP HTTP transport are now implemented. The official SDK client verifies read → draw → audit → revoke → denied action. Still connect the intended ChatGPT client on the actual private host; OAuth is not implemented. A chart iframe does not provide AI access. See ai-access.md.

## 5. Broader strategy and market validation

Complete formal CRT/ICT definitions, higher-timeframe alignment, opposing-level room, spread/news policies, exchange calendars, individual futures expiries and rollover rules. Add time-based walk-forward evaluation and uncertainty reporting. The five existing simulator variants are narrower research approximations. Test strategies independently; none is demonstrated to be profitable.

## Benefit today

With authorized imported history, the user can practice replay without future candles, inspect defined patterns, compare deterministic strategy approximations after illustrative costs, retain simulated trade notes and export/restore the workspace. This can support a repeatable learning process, but it does not establish improved outcomes. Without imported data, most research functions remain empty; the external charts alone do not deliver the master project's main benefit. There is no guarantee of returns, verified strategy edge, executable price feed, real-money execution or completed live AI assistant.
