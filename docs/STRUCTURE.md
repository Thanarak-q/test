# Structure

## Layout

```
api/
├── pyproject.toml            deps + ruff + pytest config (uv-managed)
├── alembic.ini · alembic/    migrations; env.py reads DATABASE_URL from app.config
└── app/
    ├── main.py               app assembly · CORS · error handlers · includes routers
    ├── config.py             pydantic-settings; missing env var fails at boot
    ├── db.py                 engine · SessionLocal · Base · UtcDateTime · get_session / get_unbegun_session
    ├── redis.py              get_redis → the lifespan-owned client on app.state
    ├── envelope.py           Envelope[T] · EnvelopeRoute · AppError · handlers
    ├── models.py             every ORM table imported here for autogenerate
    ├── dependencies.py       require_api_key (public API) · get_current_user (dashboard session)
    ├── routers/{f}.py        HTTP only · APIRouter(prefix="/v1/{f}", route_class=EnvelopeRoute)
    ├── services/{f}.py       the domain work; receives a session, owns the transaction
    ├── repos/{f}.py          async module functions, SQLAlchemy lives only here
    └── constants/
tests/                        pytest, asyncio_mode=auto · tests/repos/ = real MySQL + Redis

web/
├── vite.config.ts            router plugin · react · tailwind · react-compiler
├── orval.config.ts           OpenAPI → src/api/generated (API must be running)
└── src/
    ├── routes/               file-based, thin; TanStack Router generates routeTree.gen.ts
    ├── pages/{page}/         the feature: index.tsx · hooks/ · components/
    ├── api/generated/        orval output — hooks, types, query keys; never hand-edited
    ├── api/mutator.ts        orval's axios adapter: unwraps the envelope, throws ApiError(code)
    ├── utils/AxiosUtil.ts    shared axios instance (bare origin; paths carry /v1)
    ├── stores/               nanostores
    ├── components/{ui,layout}/
    └── styles/index.css      Tailwind v4 entry + theme tokens
```

## Pinned versions (checked live 2026-09-05)

|                        |                                                                           |
| ---------------------- | ------------------------------------------------------------------------- |
| Python                 | 3.11.9 · uv 0.11.17                                                       |
| fastapi                | 0.141.1                                                                   |
| sqlalchemy             | 2.0.52 (async) · aiomysql 0.3.2                                           |
| alembic                | 1.19.2                                                                    |
| pydantic               | 2.13.5 · pydantic-settings 2.15.0                                         |
| httpx                  | 0.28.1 (runtime — the LLM provider call, not just tests)                  |
| ruff                   | 0.16.6 · pytest 9.1.1 · pytest-asyncio 1.4.0                              |
| Bun                    | 1.3.14 · Node 24.19.0                                                     |
| vite                   | 8.2.2 · @vitejs/plugin-react 6.1.1                                        |
| react                  | 19.2.8 · babel-plugin-react-compiler 1.0.0 · @rolldown/plugin-babel 0.2.3 |
| typescript             | **6.0.3** — not 7.x, see DECISIONS                                        |
| tailwindcss            | 4.3.3 via @tailwindcss/vite (no PostCSS, no tailwind.config.js)           |
| @tanstack/react-router | 1.170.32 · router-plugin 1.168.35 · react-query 5.102.8                   |
| eslint                 | 10.10.0 · typescript-eslint 8.69.0 · prettier 3.9.6                       |
| vitest                 | 5.0.0 · jsdom 30.0.1                                                      |
| MySQL                  | 8.4 (compose, host port 3310)                                             |
| Redis                  | 8-alpine (compose, host port 6389) · redis-py 8.1.0                       |

## Adding a feature

1. `api/app/models.py` — table with domain prefix + `user_id`.
2. `alembic revision --autogenerate` — read the generated migration, MySQL autogenerate misses type changes.
3. `api/app/repos/{domain}.py` — async functions, `session` first, scope by `user_id`, no commit.
4. `api/app/services/{domain}.py` — the work, if it is more than one repo call.
5. `api/app/routers/{domain}.py` — `APIRouter(prefix="/v1/{domain}", route_class=EnvelopeRoute)`, then include it in `main.py`. Validate in, call the repo/service, return the DTO; the route class adds the envelope.
6. `bun run --cwd web gen:api` with the API running — never hand-write the response type in web.
7. `web/src/pages/{page}/` — page folder with its own `hooks/`.
