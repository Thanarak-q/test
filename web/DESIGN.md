---
name: Mathew AI API dashboard
description: A compact dark workspace for API keys and usage.
colors:
  background: "#202020"
  foreground: "#ededed"
  muted-foreground: "#aaa"
  border: "#383838"
  sidebar: "#131313"
  surface-hover: "#303030"
  control-border: "#535353"
  accent: "#ad9beb"
  success: "#98c9ad"
  danger: "#ffb2ac"
  focus: "#c7b9f7"
  primary-ink: "#161616"
  primary-hover: "#fff"
  primary-active: "#d1d1d1"
  danger-action: "#a13d36"
  danger-hover: "#b6473e"
  chart: "#9984ce"
  chart-hover: "#b3a0e6"
  inset: "#1e1e1e"
  notice: "#252525"
typography:
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.5
  mono:
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
    fontSize: "12px"
rounded:
  tag: "4px"
  small: "6px"
  field: "7px"
  control: "8px"
  dialog: "12px"
  filter: "20px"
spacing:
  compact: "8px"
  control: "12px"
  section: "20px"
  dialog: "24px"
  workspace: "28px"
components:
  button-primary:
    backgroundColor: "{colors.foreground}"
    textColor: "{colors.primary-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-active:
    backgroundColor: "{colors.primary-active}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
  button-danger:
    backgroundColor: "{colors.danger-action}"
    textColor: "{colors.primary-hover}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
  button-icon:
    backgroundColor: "transparent"
    rounded: "{rounded.small}"
    padding: "6px"
    size: "32px"
  input-text:
    backgroundColor: "{colors.inset}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.field}"
    padding: "8px 11px"
    height: "40px"
  nav-item:
    textColor: "#c2c2c2"
    rounded: "{rounded.control}"
    padding: "0 11px"
  demo-tag:
    backgroundColor: "#302b3d"
    textColor: "#c1b0f0"
    rounded: "{rounded.tag}"
    padding: "2px 6px"
  notice-card:
    backgroundColor: "{colors.notice}"
    rounded: "{rounded.control}"
    padding: "13px 12px"
---

# Design System: Mathew AI API dashboard

## Overview

**Creative North Star: "The restrained developer workspace"**

A restrained developer workspace follows the owner-selected OpenAI Platform reference: a near-black sidebar, charcoal content, compact sans-serif text, fine dividers, and white primary actions. Mathew AI keeps its own name and uses muted violet for data and small demo indicators.

This record describes the implemented API Keys and Usage demo. It records the built interface; live API operations and authentication remain outside the current implementation. The visual source of truth is `src/styles/index.css`, with shared behavior in `src/components/`.

**Key Characteristics:**

- Compact, left-aligned working surfaces with generous unused workspace.
- Flat tonal separation and fine borders instead of shadows.
- Small outline icons, quiet labels, and clear primary actions.
- Visible keyboard focus, responsive navigation, and explicit demo labeling.

## Colors

### Primary

Soft white foreground carries primary actions against dark primary ink; hover brightens to white and pressed state dims. Muted violet accent marks demo context, while the deeper chart violet carries usage bars and share indicators. These are functional accents, not broad surface fills.

### Neutral

The sidebar is the darkest persistent surface. Charcoal background holds the workspace; notice and hover tones separate local states. Foreground is reserved for readable content, muted foreground for supporting labels, border for dividers, and control border for interactive boundaries. Inset fields sit below the surrounding dialog tone.

Green success and warm red danger communicate state alongside text. Pale violet focus identifies keyboard position. Frontmatter preserves the source color values; `.impeccable/design.json` contains synthesized tonal ramps for inspection only, not additional implementation tokens.

## Typography

Use the system sans stack for headings, controls, and content; the code stack is reserved for credentials. Page headlines use the headline token, section headings the title token, and compact controls the label token. There is no separate display font or hero type scale.

Most table and supporting text is (11–13px). Dialog titles are (18px); chart totals are (25px), reducing to (23px) on mobile. Metrics and numeric table cells use tabular numerals. Headings tighten tracking slightly; labels retain sentence case. Empty-state descriptions cap at (48ch).

## Layout

The desktop shell has a fixed (240px) sidebar, a matching workspace offset, a header at least (70px) tall, and (28px) workspace gutters. At viewport widths up to (1100px), the rail becomes (210px), key and chart gutters become (22px), and the usage header can wrap. Usage pairs its flexible chart with a (258px) summary, reduced to (215px) at that breakpoint.

At widths up to (760px), a (53px) mobile header opens a native navigation drawer; page actions wrap below the title and gutters become (18px). Usage stacks the chart over a two-column summary. The drawer is `min(290px, 85vw)`. Buttons and filters increase to at least (38px) tall.

Tables keep their column structure and scroll horizontally. The key table has an (880px) desktop minimum and (820px) mobile minimum; the usage table has a (620px) minimum. The keys surface shows a scroll-and-actions hint when its content container is at most (880px) wide. Keep the scroll region keyboard accessible. Rows use fine bottom dividers rather than separate cards.

## Elevation & Depth

The authored dashboard CSS uses no box shadows. Tonal surfaces and one-pixel borders establish structure. Native dialogs and the mobile drawer use a black backdrop at (62%) opacity. Dialogs have a slightly lighter surface and stronger border; chart tooltips use a local dark surface above the marks. Do not add elevation merely to decorate sections.

## Shapes

Controls and notice containers share the control radius. Inputs are slightly tighter; icon buttons use the small radius. Dialogs use the larger dialog radius, while search and filter controls are pill-shaped. Status dots and avatars are circles. Chart bars have rounded upper corners (3px) and square bases. Tables remain open, rectangular, and divider-led.

## Components

### Buttons and fields

Primary buttons are white with dark text; secondary buttons are transparent with a control border; destructive confirmation uses the red action tone. Desktop buttons are at least (33px) tall. Disabled controls reduce opacity to (0.42). Icon buttons use a quiet neutral foreground and hover fill; destructive icon hover also introduces red text.

Text inputs use an inset surface, control border, and the field radius. Search wraps its input in a rounded container. All interactive controls receive a pale violet (2px) focus outline, generally offset (3px), or (2px) for fields. Search applies the outline to its container. Preserve labels and the inline error/help copy.

All three filter dropdowns use the shared `FilterSelect` component, built on Base UI Select. Pill-shaped triggers open a portaled charcoal panel below the control with a (6px) gap, (10px) corners, neutral border, highlighted rows, and a selected checkmark. Menus reposition at viewport edges, scroll when needed, and wrap long labels; triggers truncate long selections. Arrow keys, typeahead, Enter, Escape, and outside-click dismissal use the primitive's accessible behavior. Mobile option rows are at least (40px) tall. Filter values remain in URL search parameters.

### Navigation and notices

Navigation rows are at least (39px) tall, with (13px) text and small outline icons. Hover lightens the row; the current route uses the surface-hover fill and foreground text. The mobile drawer repeats the same navigation. The bordered demo notice and small violet demo tag distinguish sample content; they are not generic promotional cards. Status badges combine a small dot with a text label, turning green for active keys.

### Tables and usage chart

Table headers are muted and regular-weight; key names are slightly stronger. Long names truncate, credentials use muted monospace, numeric data aligns consistently, and row actions remain at the far right. Row hover supplies a subtle tonal fill. The violet bar chart exposes the same tooltip on hover and keyboard focus; text totals and expandable daily data complement the visualization.

### Dialogs and feedback

Native dialogs cap at (480px) wide while leaving (16px) viewport margins and scroll vertically when needed. They support Escape, labeled close controls, and focus return. Creation reveals a sample secret once, presents copy feedback in place, and allows manual selection if clipboard access fails. Revocation names the key before confirmation. Empty, loading, error, and expired-session previews reuse compact icon, heading, explanation, and recovery-action patterns.

Control colors transition over (160ms) with ease-out. Loading placeholders pulse over (1.5s) with ease-in-out. Reduced-motion preference disables animation and transitions. No entrance choreography is required by the built system.

## Do's and Don'ts

### Do:

- Do reuse the shared shell, compact controls, and existing CSS tokens.
- Do keep primary actions white and reserve violet for data and small indicators.
- Do pair status colors with text, preserve visible focus, and label icon controls.
- Do preserve table readability with scrolling and the implemented overflow cue.
- Do label sample data and sample credentials as demo content.

### Don't:

- Don't add decorative gradients, glass effects, or shadows to these flat workspaces.
- Don't turn each metric or table section into a floating card.
- Don't use oversized marketing typography inside the dashboard.
- Don't hide table actions by clipping the scroll container or shrink columns to unreadable widths.
- Don't imply the demo credentials or account are connected to a live service.
