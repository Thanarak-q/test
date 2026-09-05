# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Scope

This record applies to the `web/` app only. It describes the API key management
feature within Mathew AI, not the full Mathew AI product or the API app.

## Product Purpose

Provide the web interface for Mathew AI customers to manage their own keys for
Mathew AI's API and view usage.

## Users

Mathew AI customers managing their own API keys. This surface is not an internal
administrator console or a manager for external provider credentials.

## Capabilities and Constraints

- The first design covers full API key management: list, search, create, copy a
  newly created secret, and revoke.
- A Usage page is also in scope. Its metrics and reporting behavior remain open.
- Keys provide access to Mathew AI's API and belong to the customer managing
  them. The confirmed UX shows a new secret once, provides copy feedback, and
  requires confirmation naming the key before revocation. Backend operation
  contracts and authentication integration remain open.
- The confirmed dashboard brief is in `docs/api-dashboard-brief.md`.
- Follow the repository's `../AGENTS.md` rules and the architecture documented in
  `../docs/STRUCTURE.md` and `../docs/DECISIONS.md`.
- The web app consumes the API's results and generates API types from OpenAPI.
  It must not duplicate calculations already performed by the API.

## Brand Commitments

The parent product name supplied by the owner is **Mathew AI**. The scaffold
currently displays `matthew`; that existing label does not establish the intended
product spelling.

The owner selected [OpenAI Platform](https://platform.openai.com/home) as the
design reference for the API dashboard. Future dashboard design work should use
this reference while retaining Mathew AI's name and API key management scope.
The reference does not establish additional product capabilities.

The supplied desktop screenshots clarify this reference: a near-black sidebar
beside a charcoal workspace, compact text and outline icons, subtle dividers,
rounded controls, a muted active navigation row, and high-contrast primary
actions. Preserve that restrained dashboard direction when adapting it to
Mathew AI. Browser chrome is outside the reference interface.

## Evidence on Hand

The current frontend implements the confirmed API Keys and Usage flows with
explicitly labeled demo data. The pages are in `src/pages/api-keys/index.tsx` and
`src/pages/usage/index.tsx`; the shared shell is in
`src/components/layout/dashboard.tsx`. `README.md` describes demo behavior,
state-preview URLs, and validation. Real key management endpoints, usage data,
and authentication are not yet connected.

The owner supplied two desktop screenshots in the conversation:

- **API Keys** (`platform.openai.com/api-keys`): the primary reference. A left
  navigation rail, slim page header with actions on the right, a search and filter
  row, and an empty state centered horizontally in the upper workspace with a
  key-creation action.
- **Usage** (`platform.openai.com/usage`): a secondary layout reference. The same
  navigation shell, a header with project and date controls, a broad chart area,
  a narrow summary column on the right, and tabbed detail panels below. Accent
  color is used sparingly for data marks.

These screenshots establish the visible desktop reference, not exact font or
color tokens, mobile behavior, populated states, or interaction details. The
attachments are available in the conversation; no repository image files have
been saved. The owner subsequently confirmed a Usage page is in scope; the
specific metrics shown in the reference are not yet requirements. Billing,
projects, and the other navigation items remain reference content only.

## Open Decisions

- Key operation details: naming rules, backend operation contracts, revocation
  timing, and available metadata.
- Usage metrics, date ranges, reporting delay, available breakdowns, and whether
  spending or billing data is available.
- Authentication integration and any finer-grained permission requirements.
- Interface language and additional product-specific accessibility requirements.
  The confirmed brief covers desktop and mobile layouts, keyboard access,
  labeled controls, and accessible dialogs. English remains provisional; the
  implementation's HTML language is English to match its current copy.
- What distinguishes this feature from users' current approach to managing keys.
