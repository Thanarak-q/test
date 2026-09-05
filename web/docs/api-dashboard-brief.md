# Mathew AI API dashboard brief

Status: confirmed by the owner in the shape conversation.
Scope: `web/`. Visitor mode: Operate.

## Job and outcome

Mathew AI customers manage their own keys for Mathew AI's API and understand
their consumption. Success means creating credentials, managing existing keys,
and checking usage without needing support.

## Selected direction

Use the owner's OpenAI Platform API Keys and Usage screenshots as visual
references, retaining Mathew AI branding. Use a near-black sidebar, charcoal
workspace, compact headers, subtle borders, restrained icons, and white primary
buttons. The screenshots establish the direction, not exact font or color tokens.

The shared sidebar contains API Keys and Usage. On mobile, navigation becomes a
drawer and content stacks. Reuse the shell and common controls across both pages.

## API Keys

Place "Create new secret key" in the header, followed by search and status
filters. The planned table includes name, masked key, status, created date,
last used, and actions; metadata availability must be verified against the API.
The first-time empty state repeats the creation action.

Creation flow: name the key, create it, show the secret once, copy with visible
confirmation, then return to the list. The full secret is not available from
existing list rows. Revocation requires a confirmation naming the key and
explaining the effect. Failed requests preserve input and offer retry.

## Usage

Place date-range and API-key filters above a broad usage chart, with summary
metrics alongside and a breakdown below. Requests and tokens are the proposed
starting metrics, conditional on API support. Spending is conditional on Mathew
AI supplying billing data; do not invent pricing or consumption figures.

## States and interaction

Cover loading, first-time empty, no search results, populated, error, and
expired-session states. Distinguish unavailable usage data from actual zero
usage. Support long key names with truncation and large lists with pagination.

Provide keyboard access, labeled controls, accessible dialogs, and visible
feedback for completed actions. Preserve these affordances on mobile.

## Boundaries and delivery constraints

This is a confirmed design brief, not an implementation or API contract.
Billing management, project management, external provider credentials, and an
internal administrator console are outside scope.

Follow the existing repository architecture. Routes stay thin; page features
live under `src/pages/`. Filters belong in URL search parameters. Generate API
types from OpenAPI and consume API-computed results rather than recomputing them
in the web app.

At shaping time, the repository has only a health-check scaffold. Real key
management and usage workflows require backend support. If a subsequent build
uses demonstration data, label it clearly and do not imply that sample keys
provide working API access.

## Open decisions before implementation

- Available key metadata, naming rules, operation contracts, and revocation
  timing.
- Usage metrics, supported date ranges and breakdowns, reporting delay, and
  availability of spending data.
- Authentication integration and finer-grained permissions.
- Interface language: English is provisional from the reference; the current
  HTML shell declares Thai.
- Additional product-specific accessibility requirements beyond the agreed
  keyboard, labeling, and dialog support.

These remaining decisions were not resolved by approval of the design brief.
