Backend audit (api/app, 880 lines). Ranked biggest cut first:

1. delete: duplicate token bucket Lua — pre_auth_rate_limit.py re-implements rate_limit.py (same HGET/refill/HSET/EXPIRE, only ARGV shape differs). Keep one script (the redis.call('TIME') one), expose take_token(redis, key, capacity, refill_per_s, ttl) -> (allowed, retry_s), both callers pass their own key prefix + knobs. ~-35 lines. [app/services/pre_auth_rate_limit.py:15-42, app/services/rate_limit.py:15-38]
2. delete: require_https.py + pre_auth_rate_limit.py + _bearer_token are all unwired — zero callers in app/, llm.router itself is commented out in main.py. Either wire them (one Depends chain on the router) or drop until the auth work lands; dead code with tests is still dead. [app/main.py:10,35, app/services/require_https.py, app/routers/llm.py:62]
3. native: require_https returns a hand-built JSONResponse with a non-envelope body {"error": {"type", "message"}}. Raise AppError("http_https_required", ..., 400) — envelope handler already formats it, and the shape stops violating AGENTS.md. -8 lines. [app/services/require_https.py:4-9]
4. native: pre_auth_rate_limit raises HTTPExdomain prefix). UseAppError("ratelimit_exceeded", ..., 429) like rate_limit.py does; keeps one error path. [app/services/pre_auth_rate_limit.py:60-7
5. delete: Settings.app_tz — never read. [app/config.py:9]
6. delete: Reservation.limit — only used to re-pass into add_token_usage as the upsert's insert-side default; settle could re-read from settings.llm_token_quota/quota row. Marginal; leave if you want the upsert to stay one query. [app/services/llm_quota.py:26]
7. yagni: _trusted_proxy_addresses() — 2-line helper with one caller; inline the set comprehension. [app/services/pre_auth_rate_limit.py:113]
8. shrink: get_redis() async wrapper around a module global — Depends(lambda: redis) or import the global directly in routers; the indirection buys nothing untnt. -4 lines. [app/redis.py:8]
9. shrink: redis.eval per request re-sends the script body; redis.register_script(_BUCKET_LUA) once at module load → EVALSHA. Same lines, less bandwidth — not a cut, just the idiomatic form. [both rate_limit files]

Lean elsewhere: envelope.py, llm_quota.py, llm_provider.py, repos — no wrappers, no single-impl interfaces, deps all earn their place (no limits/slowapi needed, see earlier).
