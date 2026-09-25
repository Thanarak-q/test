# Maintainability, Scalability, Availability

How this service stays easy to change, handles load, and behaves when a dependency
fails. Each section states the rule, why it exists, and where the codebase does not
meet it yet.

---

## 1. Maintainability

### 1.1 Raw SQL lives in named repo functions

We write SQL by hand rather than through ORM query building. That keeps queries visible
and predictable on MySQL, but raw SQL scattered through services is hard to read and
easy to get wrong. So every query is wrapped in a function whose name says what it
does, and nothing outside `app/repos/` contains SQL.

A service should read like a description of the business step:

```python
key = await api_key_repo.get_active(session, key_id=key_id, user_id=user_id)
if key is None:
    raise not_found()

await api_key_repo.revoke(session, key_id=key_id, user_id=user_id)
await audit_repo.record(session, action="key.revoked", actor_id=user_id,
                        target_id=key_id, source_ip=ip)
```

Nobody reading this needs to know the table layout. Someone reading the repo function
sees the exact SQL that runs.

#### Layout

```
app/repos/
  api_key_repo.py     identity_api_keys (+ the identity_users lock row)
  audit_repo.py       identity_api_key_audit_logs, identity_auth_failure_logs
  usage_repo.py       llm_usage_logs, llm_quotas (read side)
  auth_cache.py       Redis side of key validation
  auth_database.py    adapters that give validate_api_key its own short sessions
  model_repo.py       llm_models (the whitelist)
  provider_call_repo.py llm_provider_call_logs
```

One module per table or aggregate. Services import repo modules; routers import
services. Routers never import repos. (`AGENTS.md`: `router → service → repo`.)

#### Shape of a repo function

```python
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ApiKeyRow:
    id: str
    user_id: int
    name: str
    status: str
    created_at: datetime
    last_used_at: datetime | None


_GET_ACTIVE = text("""
    SELECT id, user_id, name, status, created_at, last_used_at
    FROM identity_api_keys
    WHERE id = :key_id
      AND user_id = :user_id
      AND status = 'active'
""")


async def get_active(
    session: AsyncSession, *, key_id: str, user_id: int
) -> ApiKeyRow | None:
    """The caller's active key with this id, or None if it is not theirs or not active."""
    row = (
        await session.execute(_GET_ACTIVE, {"key_id": key_id, "user_id": user_id})
    ).mappings().first()
    return ApiKeyRow(**row) if row else None
```

#### Rules

1. **Bound parameters only.** Values go in through `:name` placeholders. Never build SQL
   with f-strings, `%`, `.format()` or concatenation — that is SQL injection, and
   a single occurrence is enough.
2. **Name the intent, not the SQL.** `get_active`, `revoke`, `count_active_for_user` —
   not `select_by_id` or `run_query`. The name is the contract the service relies on.
3. **Ownership goes in the `WHERE`.** Any function touching user-owned data takes
   `user_id` as a required keyword argument and filters on it in the query itself.
   There is no variant without it. Checking ownership in Python after fetching is how
   one user ends up reading or deleting another's data.
4. **Keyword-only arguments** (`*,`). `revoke(session, key_id=a, user_id=b)` cannot be
   called with the two ids swapped by accident; `revoke(session, a, b)` can.
5. **Return a typed dataclass, never a raw `Row`.** Callers then get autocomplete and
   type checking, and a column rename breaks in one place instead of wherever the row
   was indexed by string.
6. **Select named columns, never `SELECT *`.** Adding a column must not change what a
   function returns. This is also what stops `key_hash` from leaking into a response by
   accident.
7. **One statement per function, one purpose per statement.** If a step needs two
   statements that must succeed together, the _service_ opens the transaction and calls
   two repo functions.
8. **Mutations report what they did.** Return `rowcount` (or a bool derived from it) so
   the service can tell "updated" from "nothing matched" — revoke and delete use this to
   return 404.
9. **SQL is a module-level constant** built with `text()` once, named after its
   function. It is easy to find, diff and review.
10. **Repos never commit.** The session and transaction belong to the caller
    (`get_session` owns it per request). A repo that commits breaks the service's
    ability to make two writes atomic, such as a key change plus its audit row.
11. **Repos translate infrastructure failures.** Driver and connection errors become the
    domain error the service expects (`AuthInfrastructureError` for auth). A repo never
    swallows an error and returns `None` — `None` means "not found", and treating a
    database outage as "not found" turns a 503 into a wrong 401 or a silent bypass.

#### Testing

Repo functions are tested against real MySQL from `docker-compose`, not mocks. A mock
cannot tell you the SQL is wrong. At minimum each user-owned function has a test where
a second user's id returns nothing.

### 1.2 Other maintainability rules

- **One decision, one place.** Constants (TTLs, limits, caps) live in `app/constants/`
  with a comment giving the reason for the value. A number that appears in two files
  will eventually disagree with itself.
- **Record decisions.** Anything a reasonable person might "fix" back the wrong way —
  SHA-256 instead of bcrypt, fail closed, no redirect on HTTP — has a comment at the
  code and an entry in `docs/DECISIONS.md`.
- **No placeholder files.** An empty module looks like a finished one in a tree listing.
  Create a file when it has content.
- **ORM models and migrations agree.** Alembic migrations are the source of truth for
  the schema; `models.py` must describe the same tables. Check before merging any
  migration.

### 1.3 Where we are now

- Met: `app/repos/` holds every query as a named `text()` constant with keyword-only,
  user-scoped functions returning dataclasses; `models.py` and the migrations agree
  (`alembic check` is clean); constants live in `app/constants/` with their reasons;
  `tests/repos/test_repo_ownership.py` gives each user-owned function a second-user
  test against real MySQL.
- Documented exceptions: `api_key_repo.get_for_auth` has no `user_id` (it runs before
  the caller is known — the key record is where `user_id` comes from); the adapters in
  `auth_database.py` open their own short transactions (see its docstring). The repo
  functions themselves never commit.
- No empty placeholders remain under `api/app/`.

---

## 2. Scalability

### 2.1 Load we design for

About 500 concurrent users. The expensive part is not our CPU — it is the LLM call,
which can take tens of seconds. Everything below follows from that.

### 2.2 Rules

- **Stateless API processes.** All shared state lives in Redis or MySQL, so more API
  instances can be added behind the proxy without coordination. Nothing is kept in
  process memory that another instance would need.
- **Rate limits live in Redis, not in memory.** A per-process limiter multiplies the
  real limit by the number of instances.
- **Never hold a database connection during the LLM call.** A chat request that keeps
  its session open for the whole provider call ties up a pool connection for up to the
  full timeout. With a pool of 30, thirty slow calls stop every other request that
  needs the database — including the main application's. Do the reads, release the
  session, call the provider, then open a new session for the writes.
- **Cap concurrent outbound calls.** The provider is the slowest part and outside our
  control; a bound on concurrent calls keeps a provider slowdown from consuming every
  worker.
- **Cache what is read on every request.** Key validation (60s) and the model list
  (300s) are cached in Redis. Both are primary-key lookups, so a cache miss is cheap,
  but they happen on every call.
- **Keep log tables append-only and time-bounded.** Usage and audit logs grow with
  traffic. Index on `(user_id, created_at)` and delete by retention window so the
  tables and their indexes stay bounded.

### 2.3 Where we are now

- Met: one Redis client (the lifespan's); API-key authentication reads MySQL through
  its own short session and releases it before the handler runs; retention runs as
  `python -m app.jobs.retention` in batches, with `created_at` indexes on every log
  table.
- Met (chat pipeline): the chat route never uses `get_session`; each read and write
  opens its own short session, and none is open during the provider call. Outbound
  calls are capped at 50 in flight per process (503 past that, never a queue). The
  model list is cached in Redis (`model:enabled`, 300s).
- Still open: the retention and quota-health jobs need cron entries and their own DB
  user (`docs/DB_PERMISSIONS.md`).

---

## 3. Availability

### 3.1 What we promise

This feature runs inside the main application's backend and shares its database. The
first availability rule is therefore **this feature must not take the main application
down with it.** Its own outages are acceptable; spreading them is not.

### 3.2 Failure behaviour

| Dependency down | Behaviour                                                               | Why                                                                                                                                                   |
| --------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Redis           | 503 on API calls                                                        | Rate limits and key validation depend on it. Falling back to the database for every request would move the load onto the database the main app shares |
| Database        | 503 on API calls; cached keys still validate until their TTL            | A 401 here would tell users their valid key is broken                                                                                                 |
| LLM provider    | 503 after the timeout; quota reservation released                       | A slow provider must not hold workers indefinitely                                                                                                    |
| Audit write     | Operation fails for key changes; logged and continued for auth failures | Key changes must be attributable; auth failures are frequent and must not block                                                                       |

**We fail closed.** When a check cannot run, the request is rejected, not allowed
through. The endpoint behind these checks costs real money per call, so an outage is
the cheaper failure.

### 3.3 Rules

- **Every external call has a timeout.** Database 2s, provider connect 5s and read
  120s. No call may wait forever.
- **Infrastructure errors are 503, never 401 or 404.** Users should be told to retry,
  not that their key or resource is gone.
- **Health checks touch nothing.** `/health` must not call Redis, the database or the
  provider. Otherwise it becomes an unauthenticated way to load them, and a dependency
  hiccup makes the orchestrator restart healthy processes.
- **Release on every failure path.** Reservations and similar held resources are
  released in `finally`, not per error branch — a new failure path added later is
  otherwise the one that leaks.
- **Cache invalidation failure is an error, not a warning.** If revoking a key cannot
  clear its cache entry, the revoke reports failure so the user retries, rather than
  believing a leaked key is dead while it still works for up to 60 seconds.

### 3.4 Where we are now

- Met: fail-closed is tested against an unreachable real Redis and a real MySQL outage
  (`tests/repos/test_fail_closed.py`, `test_availability.py`); a cached key keeps
  validating while MySQL is down (the `last_used_at` write is skipped, not fatal);
  database connectivity and pool-exhaustion errors map to 503 `service_unavailable`
  everywhere; Redis has 1s connect and socket timeouts, MySQL 2s connect and 2s pool
  timeouts, and the auth lookup a 2s query budget; failed cache invalidation on revoke
  is a 500.
- Met (chat pipeline): provider timeouts are connect 5s / read 120s, a timeout is
  503; the quota reservation is released in `finally` on every path that does not
  settle it (tested by removing the release: ten tests fail); the provider call log is
  written in `finally` too.
- Known limitation, recorded rather than overlooked: no circuit breaker yet. The
  timeout and the concurrency cap already keep a slow provider from taking the
  workers; revisit with real traffic metrics.
