"""API key authentication policy."""

from datetime import timedelta

# Unknown key ids are remembered this long, so hammering one bad id costs
# one MySQL lookup per 30s. Kept close to the positive TTL so "exists" and
# "does not exist" answer in similar time.
NEGATIVE_CACHE_TTL_SECONDS = 30

# Also the documented worst case after a revoke whose cache invalidation
# failed: a revoked key can keep working for up to this long.
POSITIVE_CACHE_TTL_SECONDS = 60

# last_used_at is informational; writing it on every request would turn
# every authenticated call into a MySQL write.
LAST_USED_THROTTLE = timedelta(minutes=5)

# docs/NON_FUNCTIONAL.md §3.3: every database call has a 2s budget.
DATABASE_TIMEOUT_SECONDS = 2.0
