# Free-only operating policy

Owner requirement: use free services for every layer now. Revisit paid options after one or two months only with fresh owner approval. There is no automatic upgrade, paid subscription, brokerage connection or scheduled purchase.

## What can run without a service subscription

| Requirement | Free path | Current status / limit |
| --- | --- | --- |
| Website on iPhone | Existing GitHub Pages URL, day/night themes | Working public frontend; not private server hosting |
| Interactive charts | Open-source Lightweight Charts with permitted CSV imports | Working research charts; owner must supply real licensed history |
| Other market display | Provider-hosted display widgets | Implemented; some exact feeds are restricted; alternatives explicitly labelled |
| Research data | Files the owner has permission to analyze | CSV import working; no invented data, scraped widgets or guaranteed free ten-year Gold/Nasdaq feed |
| Drawings, replay, reports, journal | Browser computation and IndexedDB | Working within documented feature coverage; export backups before clearing browser storage |
| Private API, authentication and database | Existing Docker Compose on an available computer | Implemented and tested in CI; no hardware purchase required by software, but an iPhone alone cannot host this stack |
| AI tools | Existing authenticated MCP server | Connector transport tested; intended ChatGPT client not yet connected; no paid AI API dependency added |
| Backups | Browser export and documented PostgreSQL dump/restore | Manual procedures; no paid backup service required |
| CI | Existing GitHub Actions workflows | Uses account's included allowance; private repositories and excess usage can have limits |
| Notifications | Existing in-app replay state changes | Reliable unattended live alerts and push delivery remain incomplete |
| News/calendar | No fabricated feed | Licensed integration remains incomplete; no subscription activated |

## Enforced external-data gate

`FREE_ONLY=true` is the default in Compose and generated configuration. Missing, empty or unrecognized values also block the current Twelve Data import adapter, even if `TWELVEDATA_ENABLED=true`. Blocking occurs before loading its credential or making an outbound request. `/api/providers` reports the policy and effective enabled state.

This is an application data-adapter guard, not a cloud billing firewall. It cannot change an account's subscription or prevent charges from services configured outside this repository. No billing automation is implemented. A later approved integration must implement the same policy explicitly; setting `FREE_ONLY=false` alone does not enable a provider.

## Free cloud hosting assessment — not deployed

Official limits checked 2026-10-19:

- Supabase Free offers a 500 MB database, 1 GB file storage and 5 GB egress, with inactivity pausing. It can supply persistent Postgres, but is not a drop-in host for this Python/Next.js Docker stack. https://supabase.com/pricing
- Render Free can run web services but sleeps after 15 minutes, loses filesystem changes on restart and shares 750 instance hours across a workspace. Its free Postgres expires after 30 days. Do not store this application's database or only backup on its ephemeral disk. https://render.com/docs/free
- Render can bill bandwidth/build overages when a payment method is attached. A free plan label is insufficient to promise zero charges. Avoid enabling billing and verify account limits before resource creation.

A combined web/API runtime, persistent database configuration, private schema isolation and memory-constrained CI acceptance coverage are now implemented; see [deployment instructions and verification limits](free-cloud-deployment.md). Actual cloud provisioning and provider-specific connection/TLS checks remain pending. No free cloud resources have been provisioned. Do not run the existing two-service Compose stack on Render and assume a complete month of free continuous uptime.

The database organization choice is pending. Account administrators can access/manage project resources, so organization ownership must be selected before provisioning. Do not send database passwords or API keys in chat; use the host's secret settings when deployment is ready.

## Later paid review

Review actual storage, cold starts, supported data rights and measured workload with the owner after the trial period. Show the specific plan and monthly ceiling before activating anything paid. Upgrade only the necessary component. No promise of profitability or of a fully free licensed live feed is implied.
