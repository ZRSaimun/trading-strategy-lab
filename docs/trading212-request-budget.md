# Trading 212 owner-controlled read-only request budget (opt-in)

\`app.trading212_request_budget\` implements a durable, single-host SQLite
reservation ledger for the existing **Invest/Stocks ISA** read-only Trading 212
adapter. It is not wired into website routes, startup or a scheduler. The
optional \`fetch_budgeted_trading212_readonly\` is the only function in this
module capable of making a broker GET, and only when the owner explicitly
invokes it after provisioning. No authenticated broker call was made here.

Official Trading 212 documentation, checked 26 October 2026:
https://docs.trading212.com/api . The API is **not for CFDs**. The provider
says rate limits are **per account across API keys and IP addresses**, with
endpoint-specific windows. Local controls do **not** establish provider quota.

## Safeguards and limitations

- Operator explicitly provisions a **today-only UTC** policy with
  \`owner_confirmed=True\`, exact \`DEMO\`/\`LIVE\`, \`INVEST\`/\`STOCKS_ISA\`,
  stable **account-scope SHA-256** (not a hash of a key), and separately
  reviewed rights and entitlement evidence fingerprints. These hashes are
  operator claims, **not authenticated provider entitlements**. Existing
  daily policies cannot be changed or increased.
- At most **50 requests per UTC day**, configurable downward; at least **60
  seconds between reservations** across all three read endpoints for the
  declared account. Spacing persists across midnight and restarts.
  SQLite \`BEGIN IMMEDIATE\` serializes concurrent workers. Duplicate
  128-bit hex request IDs fail closed.
- Each reservation is irrevocable, even on timeout, error or HTTP 429.
  No automatic retry, refund or quota reset is inferred from headers.
  Clock rollback is denied; local clock accuracy is not attested.
- Ledger must be in an absolute, process-owned private directory (mode
  \`0700\`); database must be a process-owned regular single-link file
  (mode \`0600\`). No symlinks/hardlinks. Use durable private **single-host**
  storage; ephemeral Render storage is unsuitable. This is not distributed
  locking, encryption, backup validation or a defense against privileged
  filesystem tampering.
- **All keys for one broker account must share one ledger and verified scope**.
  Independent external clients or separate ledgers are not controlled.
  A caller-supplied scope hash is not independent account authentication.
- Read endpoints are \`instruments\`, \`exchanges\`, \`account_summary\` only.
  The existing adapter uses fixed official HTTPS hosts and cannot send
  orders. Account-summary results are private. These are **not** authenticated
  Gold/oil/Nasdaq CFD prices, completed-candle feeds, or executable quotes.

## Owner-only example (not activated in production)

Provision on the current UTC day in an isolated private durable directory:

\`\`\`python
import os
from datetime import datetime, timezone
from app.trading212_request_budget import (
    provision_trading212_read_budget, fetch_budgeted_trading212_readonly,
)

ledger = os.environ["T212_PRIVATE_DURABLE_LEDGER"]
scope = os.environ["T212_VERIFIED_ACCOUNT_SCOPE_SHA256"]
provision_trading212_read_budget(
    ledger, account_scope_sha256=scope, environment="DEMO",
    account_type="INVEST", utc_day=datetime.now(timezone.utc).date().isoformat(),
    max_requests=2,
    rights_evidence_sha256=os.environ["T212_RIGHTS_EVIDENCE_SHA256"],
    entitlement_evidence_sha256=os.environ["T212_ENTITLEMENT_EVIDENCE_SHA256"],
    owner_confirmed=True,
)
# Only after owner confirms scoped key permissions and intended GET:
# result = fetch_budgeted_trading212_readonly(
#     db_path=ledger, request_id=os.urandom(16).hex(),
#     account_scope_sha256=scope, endpoint="instruments",
#     environment="DEMO", account_type="INVEST",
#     api_key=os.environ["T212_API_KEY"],
#     api_secret=os.environ["T212_API_SECRET"],
# )
\`\`\`

The GET above is intentionally commented out. Never commit or log secrets,
account IDs, API responses or private scope fingerprints.

Synthetic offline tests:
\`cd backend && PYTHONPATH=. pytest -q tests/test_trading212_request_budget.py\`.

**Release gate:** Keep PR #65 draft, unmerged and undeployed until full
exact-head CI, independent account and licensing checks, authenticated staging
acceptance with owner permission, secure key lifecycle, durable backup
restoration, rollback and production health checks. No live-money order path
is enabled.
