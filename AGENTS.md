# AGENTS.md

Rules that must not be broken. Details live in `docs/STRUCTURE.md`, rationale in `docs/DECISIONS.md`.

## Shape

- One repo, two apps: `api/` (FastAPI + MySQL) and `web/` (Vite + React, Bun runtime).
- API layering: `router → service → repo`. Repos own all SQLAlchemy; services never import the ORM session builder, they receive a session.
- Web: `routes/` is thin (route definition only), `pages/{page}/` is thick (the feature).

## Non-negotiable

- Every endpoint sits under `/v1`.
- Every response is the envelope `{ success, data, error: { code, message }, meta }`. Error codes carry a domain prefix (`money_insufficient_funds`).
- Every user-owned table carries `user_id`, and every repo query scopes by it — including while the app has one user.
- Table names carry a domain prefix: `money_transactions`, not `transactions`.
- Money is an integer in the minor unit (satang). Never float.
- Times are stored UTC. Timezone conversion happens in one API layer. "Today" means Asia/Bangkok.
- Cross-module: calling another module's service is fine, calling another module's repo is not. Anything spanning domains lives in a dashboard module.
- Web never writes API types by hand — generate from OpenAPI (`bun run gen:api`).
- Web never recomputes what the API already computed.
- Global client state is nanostores, never React Context. Filter state lives in URL search params.

## Style

- Arrow functions everywhere, both sides of the repo: `export const foo = () => {}`.
- TypeScript: `type`, never `interface` (the only exception is declaration merging a framework demands, e.g. `ImportMeta`).
- Python repos are plain async module functions taking `session: AsyncSession` first. No BaseRepository, no unit-of-work. Repos do not commit — the caller owns the transaction.

## Gates before commit

`bun run gates` — typecheck · lint · test · format:check · web build, in one command.

`bun --cwd web run X` silently exits 0 without running anything (bun 1.3.14). The flag
goes after the subcommand: `bun run --cwd web X`.
