"""Tuning knobs for the chat pipeline. Values that are not measured live in config."""

# 4 chars/token is OpenAI's own rule of thumb for English. Only sizes the
# reservation — the real count from the provider replaces it on settle.
CHARS_PER_TOKEN = 4
PER_MESSAGE_TOKEN_OVERHEAD = 4

RATE_LIMIT_CAPACITY = 10
RATE_LIMIT_REFILL_PER_MIN = 20
RATE_LIMIT_TTL_S = 3600

MODEL_CACHE_TTL_S = 300

MAX_MESSAGES = 100
MAX_CONTENT_CHARS = 100_000
