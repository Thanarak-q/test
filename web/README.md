# Mathew AI dashboard

API key management and usage reporting for Mathew AI customers. The current
build is an interactive frontend demo, with clearly labeled sample data and
nonfunctional API credentials. Backend integration and authentication are not
implemented.

## Run

From this directory, run `bun run dev`, then open the URL printed by Vite.
The root URL redirects to `/api-keys`; usage reporting lives at `/usage`.

## Try the demo

- Create a named key, copy the sample secret, and close the dialog. The full
  secret is only held in the dialog; the list retains a masked value.
- Search keys, filter active/revoked statuses, or revoke a key after confirming.
- Filter usage by key and by the last 7 or 30 demo days. Switch between requests
  and tokens, inspect daily values, and export the selected report as CSV.
- On mobile, open navigation with the menu button. Wide tables scroll
  horizontally to reveal additional fields and actions.

Keys and revocations last only while the app is open; reloading restores the
sample workspace. "Reset demo keys" also restores the initial sample keys.
Usage is a fixed, synthetic historical dataset ending September 5, 2026. New
keys have no recorded activity, and revoking a key preserves its history.

Search, status, pagination, usage metric, date range, and selected key are stored
in URL search parameters. Demo data is local and never sent to the API.

## State previews

Append `?preview=empty`, `?preview=loading`, `?preview=error`, or
`?preview=session` to either route to inspect those states. Loading previews
remain visible intentionally. The error and session actions return to the normal
demo; they do not authenticate a real customer. Creating a key from the empty
preview starts a fresh sample workspace with one key and no usage.

## Validation

Run `bun run typecheck`, `bun run lint`, `bun run test`, and `bun run build` from
this directory. Run `bun run format:check` from the repository root.

The demo's tests cover secret handling, validation, revocation, first-key state,
and consistency of usage totals and date ranges. Browser verification covers
creation/copy/revocation, filtering, CSV download, state previews, mobile
navigation, and page overflow.

## Backend handoff

Local demonstration models and fixtures are in `src/stores/demo.ts`; they are
not API response types. When real endpoints exist, generate types from OpenAPI
and consume API-computed usage through the existing service/query structure.
Confirm authentication, key operation contracts, usage metrics, and reporting
latency before enabling live credentials. The current English UI is provisional.

The confirmed UX scope is in `docs/api-dashboard-brief.md`.
