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

## Out of scope until asked

- Multi-user, workspaces, invitations. `user_id` columns exist so adding it later is a
  migration rather than a rewrite, but no auth flow is built.
- Rate limiting, background jobs, caching.
- A component library. Run `shadcn add` inside `web/` when the first real component is
  needed — do not copy components in from another project (shadcn 4.x generates against
  Base UI, not Radix, so cross-project copies break).

## Tried and did not work

_(nothing yet — record dead ends here so the next session does not repeat them)_
