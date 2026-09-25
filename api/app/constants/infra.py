"""Timeouts for everything outside the process (docs/NON_FUNCTIONAL.md §3.3).

No call may wait forever: a hung dependency must become a fast 503, not a
worker stuck until the proxy gives up.
"""

# Redis answers in well under a millisecond when healthy; anything near a
# second means it is not healthy.
REDIS_CONNECT_TIMEOUT_SECONDS = 1.0
REDIS_SOCKET_TIMEOUT_SECONDS = 1.0

# Database: 2s to connect, 2s to get a pooled connection. Waiting longer
# for the pool only queues more requests behind an exhausted pool.
DB_CONNECT_TIMEOUT_SECONDS = 2
DB_POOL_TIMEOUT_SECONDS = 2.0
