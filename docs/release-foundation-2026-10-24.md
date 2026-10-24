# Foundation release reconciliation

The earlier audit/progress documents describe the original 93c703f checkout,
not current main. Before publication, this branch was reconciled with main
09b3866, which already includes historical imports, archive browsing, forecast
audits, risk previews and bounded chart pagination. Those newer implementations
were preserved. Strict boundary cursor validation remains in force; the older
proposal to round unaligned cursors was superseded. Pagination regression tests
now exercise the shared current history aggregator rather than a duplicate.

This release adds the offline ASCII/MetaTrader archive preflight validator and
regressions, plus a health revision field sourced only from a valid 40-character
Render commit SHA. This lets an operator distinguish a healthy old deployment
from a confirmed new release. No credentials or database identifiers are exposed.

The validator is a server CLI, not a new browser upload workflow. Existing
historical import functionality on main remains the production path. No schema,
provider entitlement, paid service or trading execution change is introduced.
Earlier local-only reports do not establish production deployment status.
