# matthew

FastAPI + MySQL API and a Vite/React web app in one repo.

```
api/    FastAPI · SQLAlchemy async · Alembic · MySQL
web/    Vite · React 19 · TanStack Router + Query · Tailwind v4 · Bun runtime
docs/   STRUCTURE.md (layout + pinned versions) · DECISIONS.md (why, and what failed)
        DB_PERMISSIONS.md (grants for the app's MySQL user) · planning/ (design notes)
```

## Setup

```bash
bun install                      # root tooling + web deps
uv sync --directory api --all-groups
cp api/.env.example api/.env
cp web/.env.example web/.env
docker compose up -d             # MySQL on :3310, Redis on :6389
uv run --directory api alembic upgrade head
```

## Run

```bash
bun run api    # http://localhost:8000  (docs at /docs)
bun run web    # http://localhost:5173
```

## Gates

```bash
bun run gates
```

API tests that prove fail-closed auth and key ownership run against the compose MySQL
and Redis (they create and drop a `matthew_test` database). Without the services they
skip; set `REQUIRE_INFRA=1` (CI) to make a missing service a failure instead.

## Regenerating the web API client

```bash
bun run api            # the schema is read from the running API
bun run --cwd web gen:api
```

Commit the output in `web/src/api/generated/`. If orval fails with
`Cannot find module 'ajv/dist/core'`, see DECISIONS ("Tried and did not work").

## Migrations

```bash
uv run --directory api alembic revision --autogenerate -m "add money_transactions"
uv run --directory api alembic upgrade head
```

New tables must be imported into `api/app/models.py` or autogenerate will not see them.
