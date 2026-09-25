"""API key management policy."""

# Per account, not per key: more keys never raise any limit. Small enough
# that a user can see every key on one screen and notice one they don't know.
MAX_ACTIVE_KEYS = 5

KEY_TOKEN_PREFIX = "mthw01"

# 32 base62 characters ≈ 190 bits from a CSPRNG — why SHA-256 (not a slow
# password hash) is the right hash for it.
SECRET_LENGTH = 32

# Revocation must clear auth:{key_id}; a transient Redis blip should not
# turn into a failed revoke, but a real outage must surface as a 500.
CACHE_INVALIDATION_ATTEMPTS = 3
CACHE_INVALIDATION_BACKOFF_SECONDS = 0.05
