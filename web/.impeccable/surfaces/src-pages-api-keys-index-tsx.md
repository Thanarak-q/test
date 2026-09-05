---
version: 1
slug: "src-pages-api-keys-index-tsx"
primary_target: "src/pages/api-keys/index.tsx"
related_targets: ["src/pages/usage/index.tsx"]
---

# API dashboard

Mode: Operate. Targets: API Keys and Usage in web/. Follow the owner-confirmed
web/docs/api-dashboard-brief.md and supplied OpenAI screenshots. Demo data is
explicitly labeled; real API integration, metrics and authentication remain open.

## Direction contract

THESIS: Customers manage credentials and inspect consumption in two focused workspaces.

OWN-WORLD: Charcoal workspace, darker sidebar, fine neutral dividers, compact sans text, white primary actions, muted violet data marks.

STORY: Find a key, create and copy a new secret once, revoke deliberately, then inspect usage by date and key.

FIRST VIEWPORT: A 240px sidebar anchors a compact page header. API Keys places filters above a full-width table. Usage places a broad chart beside a narrow summary. Mobile uses a drawer and stacked panels. Copy confirmation is the signature interaction; controls transition in 160ms with reduced-motion support.

FORM: Owner-pinned OpenAI Platform composition, confirmed in shape; no open concept selection or seed. Implement directly from these supplied references; no standing build-path preference is recorded.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
