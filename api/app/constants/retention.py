"""How long logs are kept, and the dashboard ranges that follow from it."""

# Usage older than this is deleted, so the dashboard cannot offer more.
USAGE_RETENTION_DAYS = 60
# Key lifecycle events must outlive a quarter's worth of investigations.
AUDIT_RETENTION_DAYS = 90
AUTH_FAILURE_RETENTION_DAYS = 90
# Metadata of every provider call, kept as long as usage.
PROVIDER_CALL_RETENTION_DAYS = 60
# A soft-deleted key keeps its row this long for the audit trail, then goes.
DELETED_KEY_RETENTION_DAYS = 90

USAGE_DEFAULT_RANGE_DAYS = 7

# Deleting in small batches keeps each transaction short, so retention
# never holds locks the request path is waiting for.
RETENTION_DELETE_BATCH = 5_000
