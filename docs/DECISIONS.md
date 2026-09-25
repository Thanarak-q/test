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

## Out of scope until asked

- Multi-user, workspaces, invitations. `user_id` columns exist so adding it later is a
  migration rather than a rewrite, but no auth flow is built.
- Background jobs, general response caching.
- A component library. Run `shadcn add` inside `web/` when the first real component is
  needed — do not copy components in from another project (shadcn 4.x generates against
  Base UI, not Radix, so cross-project copies break).

## Tried and did not work

_(nothing yet — record dead ends here so the next session does not repeat them)_
