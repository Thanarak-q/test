"""Chat pipeline policy. Every value here is referenced by the spec in
docs/planning/chat_pipeline.md; change them together with it."""

# Hard ceiling on output tokens per request, whatever the model allows. The
# effective cap is min(request.max_tokens, model.max_output_tokens, this).
POLICY_CAP = 4_096

# Unsupported request parameters are rejected, never ignored: an ignored
# `stream: true` leaves the SDK waiting for chunks that never come.
UNSUPPORTED_PARAMS = ("stream", "tools", "functions", "tool_choice", "function_call")

# Roles a caller may send. `system` is allowed because RAG needs it; the API
# itself never adds a system instruction.
ALLOWED_ROLES = frozenset({"system", "user", "assistant"})

# Per-message framing the provider adds on top of the text itself.
TOKENS_PER_MESSAGE = 4

# Outbound calls in flight per API process. Past this, 503 at once rather
# than queue: a slow provider must not consume every worker.
MAX_OUTBOUND_CONCURRENCY = 50

PROVIDER_CONNECT_TIMEOUT_SECONDS = 5.0
PROVIDER_READ_TIMEOUT_SECONDS = 120.0
PROVIDER_WRITE_TIMEOUT_SECONDS = 10.0

# A chat reply is kilobytes. Anything this large is a broken or hostile
# upstream; abort rather than buffer it.
MAX_PROVIDER_RESPONSE_BYTES = 10 * 1024 * 1024

# model:enabled is small and read on every request.
MODEL_CACHE_TTL_SECONDS = 300
# The public model list (GET /v1/public/models) is cached as one JSON string.
PUBLIC_MODELS_CACHE_KEY = "model:public"

# A reservation must outlive the slowest possible provider call by at least
# 2x, or it could expire mid-call and let the user overspend.
QUOTA_RESERVATION_TTL_SECONDS = 300
QUOTA_RESERVATION_KEY_TTL_SECONDS = 600
if QUOTA_RESERVATION_TTL_SECONDS < 2 * PROVIDER_READ_TIMEOUT_SECONDS:
    raise RuntimeError("quota reservations must outlive 2x the provider read timeout")

# Idempotency-Key replay window; matches the reservation window.
IDEMPOTENCY_TTL_SECONDS = 300

# Provider-reported prompt_tokens further than this from our own estimate is
# treated as untrustworthy, and the (slightly high) estimate is charged.
USAGE_ESTIMATE_TOLERANCE = 0.5
ESTIMATE_SAFETY_FACTOR = 1.1

# Model cache and quota store invalidation, like API key revocation.
CACHE_INVALIDATION_ATTEMPTS = 3

# The whole request body. A full prompt at the input limit is well under
# 100KB even in Thai; this refuses absurd bodies before they are parsed.
MAX_REQUEST_BODY_BYTES = 1024 * 1024
