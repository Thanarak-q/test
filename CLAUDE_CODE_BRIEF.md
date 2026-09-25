# Brief for Claude Code — API key feature

Read `AGENTS.md`, `docs/STRUCTURE.md` and `docs/DECISIONS.md` first. This brief adds
work on top of them; where it contradicts them, stop and ask rather than choosing.

## Scope

**Do:** schema, repos, session auth, API key management, usage endpoint, web wiring,
and the fixes listed under Phase 0.

**Do not touch** — the chat pipeline is being built by someone else in parallel:

```
api/app/routers/chat.py
api/app/services/provider.py
api/app/services/quota.py
api/app/services/tokens.py
api/app/services/model_catalogue.py
```

If a task below needs something from those files, define the interface you need and
leave a `TODO(chat-pipeline)` note instead of implementing it.

## Rules that are not negotiable

These come out of a threat model. Each one closes a specific hole; do not "simplify"
any of them away.

1. **Ownership is enforced in the query.** Every query touching `identity_api_keys`
   includes `user_id = :user_id` in its `WHERE`. Never fetch by id and check ownership
   in Python afterwards.
2. **Not-found and not-yours are indistinguishable.** Same status, body and headers.
3. **`user_id` comes only from the verified session or the verified key record.**
   Never from the request body, a query param, or a header. No default user id
   anywhere — delete `llm_default_user_id` from `config.py`.
4. **The plaintext secret exists once.** Generated, hashed with SHA-256, returned in the
   create response, and never stored, logged, cached, or returned again. There is no
   "show key again" endpoint.
5. **SHA-256, not bcrypt/argon2.** The secret has ~190 bits from a CSPRNG; slow hashing
   buys nothing and this runs on every request. Keep the comment explaining this.
6. **Infrastructure failure is 503, never 401 and never a silent pass.** Repos convert
   `RedisError` and database errors into `AuthInfrastructureError`. A repo that catches
   a Redis error and returns `None` breaks fail-closed for the whole system — this is
   the single most likely mistake in this codebase.
7. **Redis is a hard dependency.** When it is down, requests get 503. Do not fall back
   to querying the database on every request.
8. **`status` is the only source of truth for key validity.** `revoked_at` and
   `deleted_at` are audit data.
9. **Every key operation writes an audit row in the same transaction.** If the audit
   insert fails, the operation fails.
10. **Revocation invalidates the cache.** `DEL auth:{key_id}` with 3 retries; if it
    still fails, return 500 and log an alert — never report success. The positive cache
    TTL (60s) is the documented worst-case window if this path fails.

## Phase 0 — fixes to existing code

Do these first; later phases depend on them.

- [ ] **Health route mismatch.** `web/.env.example` points at `/v1` but `health` is
      mounted without a prefix, so the web gets 404. Set
      `VITE_API_BASE_URL=http://localhost:8000` and have each API router carry its own
      `/v1` prefix. Health stays at `/health`, unversioned and unauthenticated.
- [ ] **Two Redis clients.** `app/redis.py` creates a module-global client and
      `main.py` lifespan creates another on `app.state`. Keep the lifespan one; make
      `get_redis` read `request.app.state.redis`.
- [ ] **Restore the revoke advice** in `proxy_trust.HTTPS_REQUIRED_MESSAGE`:
      _"HTTPS is required. Update your client to use https:// and revoke this key, as
      it was transmitted unencrypted."_ A request that arrived over HTTP already leaked
      the key.
- [ ] **Move `api/adapters/` and `api/dependencies.py` into `api/app/`.** Per
      `AGENTS.md` the layer is called `repos`: use `app/repos/`.
- [ ] **`perkey_rate_limit`:**
  - Reject at startup (assert) if the largest possible single request cost exceeds
    `TOKEN_RATE_LIMIT_CAPACITY`, otherwise such a request is denied forever.
  - Emit `X-RateLimit-Tokens-Limit/Remaining/Reset` for the token bucket. Keep
    `RateLimit-*` for the request bucket only — do not report token state under the
    request headers.
  - Put `limit_type` (`requests` | `tokens`) into the 429 error code:
    `rate_limit_exceeded_requests` / `rate_limit_exceeded_tokens`.
  - Rename bucket key `rl:key:{user_id}` → `rl:req:{user_id}`.
- [ ] **Update `docs/DECISIONS.md`:** it still says rate limiting is out of scope.
      Record the pre-auth and per-key limiters and why.
- [ ] **Convert `docs/Bas/new-req.md`** from Excalidraw JSON to readable markdown, and
      rename `docs/Bas/` → `docs/planning/`.

## Phase 1 — schema

The ORM and the migration currently describe different databases: the migration never
creates the `identity_*` tables, and `llm_models` has different columns in each.
Replace with one migration that matches `models.py`. Coordinate `llm_models`, `llm_quotas`
and `llm_usage_logs` with the chat pipeline owner before changing them.

`identity_api_keys`

| column       | type                        | notes                                                                                                                     |
| ------------ | --------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| id           | `String(26)` PK             | ULID. **Not** an autoincrement int — `validate_api_key` rejects anything that is not a ULID, so every key currently fails |
| user_id      | FK, indexed                 |                                                                                                                           |
| name         | `String(100)` not null      |                                                                                                                           |
| key_hash     | `CHAR(64)` not null, unique | SHA-256 hex                                                                                                               |
| status       | `String(10)` not null       | CHECK in (`active`, `revoked`, `deleted`)                                                                                 |
| created_at   | tz datetime not null        |                                                                                                                           |
| revoked_at   | tz datetime null            |                                                                                                                           |
| deleted_at   | tz datetime null            |                                                                                                                           |
| last_used_at | tz datetime null            | required by `validate_api_key`'s cache record                                                                             |

Index `(user_id, status)`.

`identity_api_key_audit_logs` — add `target_id String(26)` with an index. Without it
an audit row says a key was revoked but not which one.

`llm_models` — rename `max_tokens` → `context_window`, not null. `max_tokens` in a chat
request means the output cap; reusing the name for the model's total window invites a
bug where the output cap is set to the whole window.

DB permissions (document in `docs/`, do not assume): the app user needs INSERT only on
audit and log tables — no UPDATE or DELETE there.

## Phase 2 — repos

In `app/repos/`, implement the three protocols declared in
`app/services/validate_api_key.py`:

- `RedisAuthCache` — use `negative_cache_key` / `positive_cache_key`, never hardcode
  key strings. Serialise `last_used_at` as ISO-8601 with timezone and parse it back to
  an aware `datetime`; `_validate_record` rejects naive datetimes.
- `SqlAuthDatabase` — enforce `timeout_seconds` for real (e.g. `asyncio.wait_for`).
- `SqlFailureAudit` — write `auth.failed` with `key_id`, `source_ip`, `reason`.

Each one raises `AuthInfrastructureError` on any infrastructure failure.

**Tests required** (`tests/repos/`): with Redis unreachable, `validate_api_key` raises a
503 `HTTPException` and does **not** call the database. This is the test that proves
fail-closed works; the existing tests use fakes and cannot.

## Phase 3 — session auth

Key management is called from the browser with the main application's session, not
with an API key. Nothing in the backend verifies a session yet.

**Stop and ask before implementing** how the main application's session works
(cookie name, JWT or server-side, whether this service can verify it locally). Then:

- One dependency, `get_current_user(request) -> int`, that returns the verified user id
  or raises 401.
- A dev override that works only when `ENV=dev` and is impossible to enable otherwise.
  Assert this at startup.
- No fallback user id in any environment.

Role for admin routes is resolved here too, and checked again inside each admin service
function — not only at the route.

## Phase 4 — key management

Routes under `/v1/api-keys`, all `POST`, all requiring `get_current_user`.

Key format: `mthw01_{ulid}_{secret}` where `secret` is 32 chars base62 from
`secrets`. Display prefix: `mthw01_{ulid}` — built by the backend and returned as
`key_prefix`. The frontend never builds it.

**create** `{name}` → `{id, name, key, key_prefix, created_at}`

- `name` required, 1–100 chars, validated server-side.
- Insert only while the user has fewer than `MAX_KEYS = 5` active keys, enforced in a
  single statement so two concurrent creates cannot both pass. Otherwise 409.
- Insert + audit (`key.created`, `target_id`, `source_ip`) in one transaction.
- `secret` stays a local variable; never attach it to an ORM object.
- Response header `Cache-Control: no-store` (already global — verify it applies).

**list** → `[{id, name, key_prefix, status, created_at, last_used_at, never_used}]`

- `WHERE user_id = :u AND status != 'deleted'`, newest first.
- Serialise with an explicit allowlist of fields; `key_hash` must be impossible to leak
  by adding a field to the model.

**revoke** `{id}` → `ok` | 404

- `UPDATE ... SET status='revoked', revoked_at=COALESCE(revoked_at, now())
WHERE id=:id AND user_id=:u AND status != 'deleted'`
- Idempotent: revoking twice returns 200. Audit only when the status actually changed.
- Then invalidate cache (rule 10).

**delete** `{id}` → `ok` | 404

- Soft delete: `status='deleted'`, `deleted_at=COALESCE(deleted_at, now())`, same
  ownership clause, idempotent, audited, cache invalidated like revoke.

**Tests required:**

- User B revoking and deleting user A's key gets 404, and A's key still authenticates.
- 404 body for "someone else's key" is byte-identical to "key does not exist".
- Ten concurrent creates at 4/5 keys produce exactly one success.
- `list` response contains no `key_hash`, no secret, no secret fragment.

## Phase 5 — usage

`GET /v1/usage?from=&to=&key_id=` for the logged-in user.

- Remaining quota is shown **here only**. The public API never returns remaining quota,
  because the quota is shared with the main app and an API caller may not be the
  account owner.
- Split usage by source (`api` vs web) — users will otherwise not understand why quota
  ran out.
- Clamp the date range to the retention window (60 days).
- Depends on the chat pipeline's usage log — agree the schema with its owner.

## Phase 6 — web

- Run `bun run gen:api` and replace the hand-written `HealthService` types and
  `stores/demo.ts` with generated hooks. `AGENTS.md` forbids hand-written API types.
- **Remove `getDemoKeyPrefix`.** It slices eight characters of the secret to use as a
  display prefix — that leaks part of the secret. Show `key_prefix` from the API.
- Keep the existing create-key modal behaviour: key held in component state only, masked
  by default, auto-mask after 60s, cannot be closed by Esc or outside click, "I've saved
  it" to close, a discard action that calls delete.
- Revoke/delete: confirm with the key name in the text. On 500 from a failed cache
  invalidation, show "not revoked yet, try again" — never show success.
- Lint rule: `no-restricted-globals` for `localStorage` and `sessionStorage` in the key
  management files. (`stores/theme.ts` uses persistent storage legitimately — scope the
  rule to the key files.)

## Definition of done for each phase

- Tests for the listed cases pass, including the ones that need real Redis/MySQL (use
  the compose services, not fakes, for the fail-closed and IDOR tests).
- `docs/DECISIONS.md` records any decision made along the way and why.
- No new file under 1 line left behind as a placeholder.

## Open questions — ask, do not guess

1. How does the main application's session work? (blocks Phase 3–6)
2. Quota design: `DECISIONS.md` says Redis `INCRBY` counter re-seeded from MySQL; the
   design doc says a sorted set of reservations with TTL. Which one? (owned by the chat
   pipeline — confirm with its owner)
3. Does the main application update quota with an atomic increment or read-modify-write?
   If the latter, concurrent updates from both systems lose deductions.
4. Does nginx set `proxy_set_header X-Real-IP $remote_addr` and
   `proxy_set_header X-Forwarded-Proto $scheme`? Both proxy checks depend on it.
