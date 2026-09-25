# Decisions

## 2026-09-05 — scaffold

**One repo, two apps.** `api/` and `web/` live side by side rather than in separate
repos. Chosen by the owner. Cost: one lockfile per ecosystem and hooks that have to
route by path. Benefit: one clone, one branch per change that spans both sides.

**MySQL, not Postgres.** Owner's call. Consequences to remember: no `JSONB` (use `JSON`),
no array columns, `utf8mb4` collation set explicitly in compose, and Alembic autogenerate
is weaker on MySQL type changes — read every generated migration.

**aiomysql, not asyncmy.** asyncmy is faster but needs a C toolchain, which makes it a
recurring Windows install failure. aiomysql is pure Python. Revisit if the driver ever
shows up in a profile.

**Bun as the web runtime, uv for the API.** Bun was rejected for Next.js elsewhere
(breaks image optimization and `next/font`); neither applies to Vite.

**TypeScript 6.0.3, not 7.0.2.** `typescript-eslint@8.69.0` declares a peer of
`typescript >=4.8.4 <6.1.0`. TS 7 makes eslint fail on the first run. Revisit when
typescript-eslint ships TS 7 support.

**React Compiler wired through `@rolldown/plugin-babel`.** `@vitejs/plugin-react` v6
dropped its `babel` option, and the compiler otherwise does nothing with no error at all.
Consequence: no hand-written `useMemo` / `useCallback` / `memo`.

**No `eslint-plugin-tailwindcss`.** It needs `settings.tailwindcss.cssConfigPath` in a
config object with no `files` restriction or it searches for a Tailwind v3 config and
crashes. Class sorting comes from `prettier-plugin-tailwindcss` instead, which needs no
such wiring.

**Envelope via a custom `APIRoute`, not a middleware.** The route class wraps only
`JSONResponse`, so streaming, SSE, file and redirect responses pass through untouched.
A middleware would have had to re-buffer every response body to tell them apart.

## 2026-09-05 — chat pipeline (ported from Thanarak-q/MatthewAPI)

**Quota reserves before the call, reconciles after.** The source repo checked usage
before the provider call and wrote it in a `BackgroundTask` after, so N concurrent
requests all read the same pre-call total and all passed — the limit was advisory.
Now: `INCRBY` an estimate (prompt chars/4 + `max_tokens`), reject and roll back if it
breaks the limit, then `INCRBY (actual - estimate)` once the provider reports usage.
Consequence: the estimate must never undershoot badly or bursts overspend between
reserve and settle; `llm_output_reserve` is the knob.

**Redis holds the counter, MySQL holds the truth.** The source repo's counters carried
a 24h TTL, so an expiry silently reset usage to zero. The counter now has no TTL and is
re-seeded from `llm_quotas.token_used` with `SET NX` whenever the key is absent.

**Model whitelist in the DB, cached in Redis (300s).** Was a hardcoded
`ALLOWED_MODELS` list in settings — changing it needed a redeploy. Fail-closed: an
empty table allows nothing, so the migration seeds `gpt-4o` and `gpt-4.1`.

**httpx, not the `openai` SDK.** The pipeline makes one POST to an OpenAI-compatible
`/chat/completions`. A vendor SDK for one request buys retries we do not want in front
of a quota reservation.

**Usage is written in the request transaction, not a background task.** The source repo
opened a second session from a fire-and-forget task; a failure there lost the accounting
silently. Here `get_session` already owns the transaction.

## 2026-09-25 — rate limiting and API key groundwork (Phase 0 of `CLAUDE_CODE_BRIEF.md`)

**Rate limiting is in scope now: two limiters, before and after auth.** The public API
is authenticated by API key and every call costs real money at the provider.

- _Pre-auth, per IP_ (`rl:ip:{ip}`, 60 burst, 1/s). Runs before key validation so a
  flood of random keys is rejected before it reaches Redis lookups or MySQL. The IP
  comes only from `X-Real-IP` on a request whose peer is a trusted proxy. A request
  that then authenticates gets its token refunded, so the bucket counts failures only
  and a user who fixes a misconfigured key is not locked out.
- _Per key, after auth_ (`rl:req:{user_id}` requests, `rl:tok:{user_id}` estimated
  tokens). Keyed by the `user_id` from the verified key record, never the request.
  One Lua script checks both buckets before debiting either, so a denial leaves no
  state behind; Redis `TIME` is the only clock so workers cannot disagree.
- Both fail closed with 503 when Redis is down. Letting unchecked traffic through to a
  paid provider is worse than a short outage.

**Two header sets, never mixed.** `RateLimit-*` is the request bucket only;
`X-RateLimit-Tokens-*` is the token bucket. Reporting token counts under the request
names would give clients a number of the wrong unit to back off on. Both sets are sent
on every per-key response, allowed or denied.

**The 429 code names the bucket.** `rate_limit_exceeded_requests` /
`rate_limit_exceeded_tokens`, so a client can tell "slow down" from "send less".

**The token bucket must hold the largest request.** Startup raises if
`MAX_INPUT_TOKENS > TOKEN_RATE_LIMIT_CAPACITY`: such a request would pass the 413 check
and then be denied forever. `raise`, not `assert`, so `python -O` cannot remove it.

**Each router carries its own `/v1` prefix and `route_class=EnvelopeRoute`.**
FastAPI 0.14x keeps an included router's routes with their own class, so setting
`EnvelopeRoute` on `app.router` alone left `/health` returning bare JSON; the web's
unwrapper then threw. `tests/test_main.py` fails if any route is not enveloped.
`/health` stays unversioned and unauthenticated. The web base URL is the bare origin
(`http://localhost:8000`) and callers include `/v1` in their paths.

**One Redis client, owned by the lifespan.** `get_redis` returns
`request.app.state.redis`. The module-level client it replaced opened a second pool
that nothing ever closed.

**No default user id.** `llm_default_user_id` is gone from settings. A `user_id`
comes from a verified session or a verified key record, nothing else.

**`api/adapters/` and `api/dependencies.py` deleted, not moved.** They were empty; the
layer they were meant to be is `app/repos/`, which arrives with real code in Phase 2
rather than as empty placeholders.

## 2026-09-25 — API key feature (phases 1–6 of `CLAUDE_CODE_BRIEF.md`)

**One migration, matching the ORM.** The old migration never created `identity_*`
and described a different `llm_models`. Replaced by `20260925_schema`; `alembic check`
is clean against it. Databases built from the old migration must be recreated.

**`UtcDateTime` is the one place zones are handled on the way to and from MySQL.**
`DATETIME` has no zone and the driver returns naive values, which `validate_api_key`
rightly rejects. The column type refuses naive writes, stores UTC, and tags reads UTC.
`DATETIME(6)` so "newest first" is stable. No server-side time defaults: `NOW()`
follows the session zone, so the app sets every timestamp (and pins the session to
`+00:00` anyway).

**`llm_models.max_tokens` → `context_window`.** In a chat request `max_tokens` is the
output cap; sharing the name invites setting the output cap to the whole window.

**Auth failures get their own table, `identity_auth_failure_logs`.** The key id comes
from an unauthenticated caller: it may not exist, so it cannot carry a `user_id` or
FK, and an attacker controls the write rate. Key lifecycle events stay in
`identity_api_key_audit_logs`, now with `target_id`.

**`SqlFailureAudit` commits its own transaction.** The one repo adapter that does: a
failed authentication raises 401, which rolls back the request transaction, so a row
written there would never land.

**Redis repos never return `None` on `RedisError`.** `None` means "not cached", so the
caller would fall through to MySQL on every request — fail-open disguised as a miss.
`tests/repos/test_fail_closed.py` runs against an unreachable real Redis and fails if
any cache method swallows the error, or if MySQL is touched.

**Key creation: per-user row lock, then one conditional `INSERT … SELECT`.** The
count-and-insert is one statement, but on its own it deadlocks under concurrency: each
transaction takes shared gap locks, then each waits on the other's to insert (verified
— the concurrency test fails with MySQL error 1213 without the lock). Locking the
user's `identity_users` row first (`INSERT … ON DUPLICATE KEY UPDATE`, which also
creates the mirror row) serialises creates per user. Ten concurrent creates at 4/5
yield exactly one success.

**Key management services own their transaction** (`get_unbegun_session`). Revoke and
delete must invalidate `auth:{key_id}` _after_ the new status is committed; otherwise
a concurrent lookup could read the old status and re-cache it. The idempotent path
invalidates too, so retrying a revoke whose invalidation failed actually helps.

**Revoke/delete are idempotent; audit only on change.** Revoking a deleted key is 404,
the same 404 as someone else's key and a key that never existed (byte-identical body
and headers, tested).

**Request bodies forbid extra fields.** A body carrying `user_id` is a 422, not
silently ignored.

**Session auth fails closed until the main app's session is known.**
`_verify_main_app_session` returns nothing (`TODO(session)`, open question 1), so every
dashboard request is 401 except under the dev override: `ENV=dev` plus
`DEV_SESSION_USER_ID`. `ENV` defaults to `production`, startup refuses the override
outside dev, and the override is re-checked per request. CORS still disallows
credentials; revisit once the session mechanism is known.

**Usage lives in a dashboard module and resolves dates in the API.** "Last N days"
is a `days` parameter, not dates computed in the browser, so "today" is always Asia/
Bangkok's. SQL groups by UTC hour; Python buckets hours into Bangkok days. Ranges are
clamped to the 60-day retention window. Remaining quota is returned here only.

**Web: generated client over axios.** orval 8 defaults to a fetch client whose
signature does not match the axios mutator; `httpClient: "axios"` keeps one transport.
`listApiKeys` is POST (no key ids in URLs) but generated as a query. The mutator throws
`ApiError` with the envelope's `code`, so the UI can tell "revocation pending" (500)
from other failures and never shows it as success.

**`key_prefix` comes from the API.** The demo's `getDemoKeyPrefix` sliced characters
off the secret for display — that leaked part of it. The prefix is now
`mthw01_{key_id}`, built server-side, containing nothing of the secret.

## 2026-09-25 — non-functional rules (`docs/NON_FUNCTIONAL.md`)

**Repos are raw SQL in named functions.** Every query is a module-level `text()`
constant named after its function, with bound parameters only (the `DATE_FORMAT`
pattern too), keyword-only arguments and dataclass results. Modules are per table:
`api_key_repo`, `audit_repo`, `usage_repo`. Routers and `dependencies.py` never import
repos; services construct the Redis/MySQL adapters.

**Auth reads MySQL through its own short session.** `SqlAuthDatabase` takes the session
factory rather than the request's session, so an API-key request releases its pooled
connection as soon as the key is looked up — the precondition for the chat route not
holding one across the provider call.

**A failed `last_used_at` write no longer rejects a cached key.** The availability
table says cached keys keep validating while MySQL is down until their TTL. The write
is informational, so its failure is logged and the record is not re-cached; a cache
miss with MySQL down is still 503. This relaxes brief rule 6 for this one write only.

**Connectivity errors are 503 app-wide.** `OperationalError`, `InterfaceError`,
`DisconnectionError`, pool `TimeoutError` and `RedisError` map to `service_unavailable`;
an `IntegrityError` (a bug) stays a 500.

**Every external call has a timeout** (`app/constants/infra.py`): Redis 1s connect and
socket, MySQL 2s connect and 2s pool wait.

**`X-Request-Id` on every response.** The public docs tell users to quote it, and audit
rows had a `request_id` column that nothing filled. An incoming id is kept only from
the trusted proxy (so nginx's `$request_id` can tie logs together), otherwise replaced.
Identical-404 checks compare every header except this one, which is unique per request
by design.

**Retention job.** `app/jobs/retention.py` deletes in batches of 5,000, one short
transaction each, so it never holds locks the request path waits on; `created_at`
indexes (migration `20260925_retention`) keep each batch off a table scan. Audit and
auth-failure logs keep 90 days, usage 60.

## 2026-09-25 — public docs (`/docs`)

**Every value comes from `web/src/content/docs/values.ts`.** Pages name a value by path
(`<Value path="limits.tokens.capacity" />`) and code samples are built from it in
`samples.ts`. `values-only.test.ts` reads each `.mdx` from disk and fails if any value
from `values.ts` appears literally. Placeholders are deliberately fake (`TBD`, `0` in a
limit or context window, a `.invalid` URL) and render as a "To be confirmed" badge.

**The release build refuses placeholders; the gates build does not.** `bun run --cwd web
build` runs `placeholders.test.ts` in production mode first, which fails while any
placeholder is left. The values are TBD by design until launch, so `bun run gates` uses
`build:check` (compile and typecheck only) instead. Switch release pipelines to `build`.

**Docs render inside the dashboard layout,** with their own grouped sidebar, and call no
API, so they read the same signed out. One splat route (`/docs/$`) looks pages up in
`pages/docs/nav.ts`; each page's MDX chunk loads lazily.

**Preview badges on every endpoint page, not only the three the brief named.** Chat,
embeddings and models are all served by the chat pipeline, none of which exists yet;
"document only what exists" applies to all three references.

**Errors document the envelope the API returns today** (`error.code`, e.g. `http_401`,
`rate_limit_exceeded_tokens`). If the chat pipeline returns OpenAI-shaped errors for SDK
compatibility, the Errors page and chat reference change with it.

## 2026-09-25 — chat pipeline (`docs/planning/chat_pipeline.md`)

**The chat pipeline is built here after all.** The brief kept its five files for
another developer; that work was handed back, and this implements the spec as given.

**Quota lives in the main application's Redis hash, not MySQL.** Supersedes the
2026-09-05 "Redis holds the counter, MySQL holds the truth" entry and open question
2: `quota:{user_id}` (`limit`, `used`) is the main app's; our in-flight reservations
are a sorted set beside it, summed live, so nothing is left behind by a crash.
`llm_quotas` is dropped. Open question 3 still stands: the main app must update
`used` with HINCRBY, or our increments are overwritten.

**The chat reply is not wrapped in the envelope.** The one exception to AGENTS.md's
envelope rule: OpenAI SDKs cannot read `{success, data}`. Errors still use the
envelope — the SDKs read `error.message` from it. `tests/test_main.py` allows exactly
this one unwrapped route.

**Proof objects instead of ids.** `ValidatedModel` and `Reservation` can only be built
by `model_validate` and `quota_reserve` (a module-private token checked in
`__post_init__`), so `proxy_to_llm` cannot be reached by a path that skipped them.

**model_validate reads MySQL when Redis is down.** The one deliberate fail-open in
the chain, as specified: a tiny primary-key read. The request still needs Redis for
the rate limit and quota a moment later, so it 503s there anyway.

**Estimates use UTF-8 bytes / 4.** Characters / 4 undercounts Thai badly (three bytes
per character, about a token per character); bytes / 4 stays on the high side for
Thai and is right for English.

**The per-key 413 ceiling is input limit + output cap.** The estimate now includes
the output cap, so the old `est > MAX_INPUT_TOKENS` check would have refused valid
requests. Startup still checks the token bucket can hold the largest request.

**Alembic keeps existing loggers.** `fileConfig` disabled every app logger when
migrations ran in-process, silencing ALERT lines; `disable_existing_loggers=False`.

## Out of scope until asked

- Multi-user, workspaces, invitations. `user_id` columns exist so adding it later is a
  migration rather than a rewrite, but no auth flow is built.
- General response caching. (The retention job is the one scheduled job; anything
  else scheduled needs asking first.)
- A component library. Run `shadcn add` inside `web/` when the first real component is
  needed — do not copy components in from another project (shadcn 4.x generates against
  Base UI, not Radix, so cross-project copies break).

## Tried and did not work

**`gen:api` fails with `Cannot find module 'ajv/dist/core'`.** bun hoists
`ajv-draft-04` (from orval's `@scalar/openapi-parser`) to the root, next to eslint's
ajv 6, but it needs ajv 8. Local workaround, not committed:
`ln -sfn ../../@scalar/openapi-parser/node_modules/ajv node_modules/ajv-draft-04/node_modules/ajv`.
Proper fix is still open (an isolated linker, or an override once bun supports
nested ones).
