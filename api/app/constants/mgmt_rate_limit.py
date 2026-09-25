"""Rate limits on the dashboard's key management endpoints, per user.

Reads are cheap and happen on every page load; writes create secrets and
audit rows, so their cap is lower.
"""

READ_CAPACITY = 60
READ_REFILL_PER_SECOND = 1.0
WRITE_CAPACITY = 10
WRITE_REFILL_PER_SECOND = 10 / 60
BUCKET_TTL_SECONDS = 3600
