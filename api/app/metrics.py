"""Prometheus metrics for the chat pipeline (docs/planning/chat_pipeline.md).

Served at /metrics to the trusted proxy and localhost only; see main.py.
"""

from prometheus_client import Counter, Gauge, Histogram

provider_calls = Counter(
    "llm_provider_calls_total",
    "Provider calls by outcome (ok, timeout, provider_error, rate_limited, "
    "bad_response, too_large).",
    ["outcome"],
)

usage_validation_failures = Counter(
    "llm_usage_validation_failures_total",
    "Provider usage figures that failed validation and were replaced by our "
    "estimate. Divide by llm_provider_calls_total{outcome='ok'} for the rate.",
)

estimate_gap = Histogram(
    "llm_prompt_estimate_ratio",
    "Provider prompt_tokens divided by our estimate. 1.0 is a perfect estimate.",
    buckets=(0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 4.0),
)

outbound_in_flight = Gauge(
    "llm_outbound_in_flight",
    "Provider calls in flight in this process.",
)

outbound_rejected = Counter(
    "llm_outbound_rejected_total",
    "Requests refused because the outbound concurrency cap was reached.",
)

idempotent_replays = Counter(
    "llm_idempotent_replays_total",
    "Requests answered from a stored response via Idempotency-Key.",
)
