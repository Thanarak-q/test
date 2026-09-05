# Structure

## Layout

```
api/
├── pyproject.toml            deps + ruff + pytest config (uv-managed)
├── alembic.ini · alembic/    migrations; env.py reads DATABASE_URL from app.config
└── app/
    ├── main.py               app assembly · CORS · error handlers · mounts /v1
    ├── config.py             pydantic-settings; missing env var fails at boot
    ├── db.py                 async engine · SessionLocal · Base · get_session
    ├── envelope.py           Envelope[T] · EnvelopeRoute · AppError · handlers
    ├── models.py             every ORM table imported here for autogenerate
    ├── routers/{f}.py        HTTP only — no business logic
    ├── repos/{f}.py          async module functions, SQLAlchemy lives only here
    └── constants/
tests/                        pytest, asyncio_mode=auto

web/
├── vite.config.ts            router plugin · react · tailwind · react-compiler
├── orval.config.ts           OpenAPI → src/api/generated (API must be running)
└── src/
    ├── routes/               file-based, thin; TanStack Router generates routeTree.gen.ts
    ├── pages/{page}/         the feature: index.tsx · hooks/ · components/
    ├── services/{X}Service/  index.ts + types/{XRequest,XResponse}.ts
    ├── api/mutator.ts        orval's axios adapter (unwraps the envelope)
    ├── utils/AxiosUtil.ts    shared instance + typed get/post/patch/delete
    ├── consts/queryKeys.ts   query key factory
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
| ruff                   | 0.16.6 · pytest 9.1.1 · pytest-asyncio 1.4.0 · httpx 0.28.1               |
| Bun                    | 1.3.14 · Node 24.19.0                                                     |
| vite                   | 8.2.2 · @vitejs/plugin-react 6.1.1                                        |
| react                  | 19.2.8 · babel-plugin-react-compiler 1.0.0 · @rolldown/plugin-babel 0.2.3 |
| typescript             | **6.0.3** — not 7.x, see DECISIONS                                        |
| tailwindcss            | 4.3.3 via @tailwindcss/vite (no PostCSS, no tailwind.config.js)           |
| @tanstack/react-router | 1.170.32 · router-plugin 1.168.35 · react-query 5.102.8                   |
| eslint                 | 10.10.0 · typescript-eslint 8.69.0 · prettier 3.9.6                       |
| vitest                 | 5.0.0 · jsdom 30.0.1                                                      |
| MySQL                  | 8.4 (compose, host port 3310)                                             |

## Adding a feature

1. `api/app/models.py` — table with domain prefix + `user_id`.
2. `alembic revision --autogenerate` — read the generated migration, MySQL autogenerate misses type changes.
3. `api/app/repos/{domain}.py` — async functions, `session` first, scope by `user_id`, no commit.
4. `api/app/routers/{domain}.py` — validate in, call the repo/service, return the DTO; the route class adds the envelope.
5. `bun run gen:api` with the API running — never hand-write the response type in web.
6. `web/src/pages/{page}/` — page folder with its own `hooks/`.
