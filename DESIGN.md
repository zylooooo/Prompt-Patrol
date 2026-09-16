---
name: Prompt Patrol
description: Instructor-facing triage tool for flagging potentially AI-generated short student answers
colors:
  background: "#f9fafc"
  surface: "#ffffff"
  surface-muted: "#eef0f8"
  surface-modal: "#ffffff"
  modal-muted: "#f5f6fb"
  surface-strong: "#dee2f0"
  border: "#d9ddec"
  foreground: "#1e2030"
  muted-foreground: "#585d75"
  disabled-foreground: "#9ca0b4"
  primary: "#4338ca"
  primary-hover: "#3730a3"
  primary-soft: "#e4e4fa"
  primary-border: "#b3b2f0"
  primary-foreground: "#ffffff"
  secondary: "#5a6080"
  secondary-hover: "#474c69"
  secondary-soft: "#e8eaf3"
  secondary-border: "#c8ccde"
  secondary-foreground: "#ffffff"
  accent: "#6366f1"
  accent-hover: "#4f46e5"
  accent-soft: "#ebecfe"
  accent-border: "#bdbff6"
  accent-foreground: "#1e2030"
  danger: "#b91c1c"
  danger-hover: "#991b1b"
  danger-soft: "#fee2e2"
  danger-border: "#fca5a5"
  danger-foreground: "#ffffff"
  danger-on-primary: "#ffb3b3"
  warning-soft: "#fffbeb"
  warning-border: "#fcd34d"
  status-ready: "#1a7038"
  status-warming: "#924a0a"
  status-down: "#b91c1c"
  flag: "#924a0a"
  flag-soft: "#fdeede"
  human: "#1a7038"
  human-soft: "#e4f4ea"
  unsure: "#545a78"
  unsure-soft: "#e9ebf3"
  table-header: "#d8ddf0"
  table-row-hover: "#f6f7fc"
  table-selected: "#e4e4fa"
  table-border: "#d9ddec"
  focus-ring: "#6366f1"
typography:
  body:
    fontFamily: "Figtree, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  title:
    fontFamily: "Figtree, ui-sans-serif, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.3
  mono:
    fontFamily: "'DM Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "6px"
  md: "8px"
  lg: "8px"
  xl: "12px"
  full: "9999px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.lg}"
    padding: "12px 16px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.lg}"
    padding: "10px 14px"
  button-secondary-hover:
    backgroundColor: "{colors.surface-muted}"
  button-destructive:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.danger-foreground}"
    rounded: "{rounded.lg}"
  button-ghost:
    textColor: "{colors.muted-foreground}"
    rounded: "{rounded.lg}"
---

# Design System: Prompt Patrol

## Overview

**Creative North Star: "The Instructor's Command Deck"**

Prompt Patrol reads as an instrument panel for a serious, evidence-based
decision — not a consumer dashboard. A fixed deep-indigo sidebar acts as
the deck's control column: wordmark, navigation, and identity anchored in
one place while the workspace beneath it stays a calm, near-white surface
tuned for reading and comparing evidence. Score readouts, timestamps, and
detector status render in monospace (DM Mono) against a sans-serif
(Figtree) interface voice, giving numeric/technical facts a distinct,
deliberate register from prose and UI copy.

Color is otherwise conserved. The palette is a single indigo family
(primary, accent, and their soft/border steps) doing almost all of the
UI's decorative work, with saturated color spent only where it carries
meaning: the three verdict colors (flag/human/unsure) and the three
detector-status colors (ready/warming/down) are deliberately separate
token families from each other and from the neutral indigo chrome, so a
"service is up" signal and a "flagged as AI" signal can never be
mistaken for one another.

**Key Characteristics:**
- Fixed indigo command-column sidebar; flat, light workspace for content
- Verdict and status color are their own token families — never reused for decoration
- Numeric/technical facts (scores, timestamps, model status) always render in DM Mono; everything else in Figtree
- Flat by default; shadow reserved for surfaces that float above the workspace (cards, modals)
- Precise, restrained component feel — no scale/glow theatrics on hover or focus

## Colors

A near-monochrome deep-indigo system: one hue family carries chrome, structure, and default accents, while verdict and status signals live in their own reserved token families so meaning is never ambiguous.

### Primary
- **Deep Indigo** (`#4338ca`): the sidebar's ground, primary CTAs, and the input focus border. This is the one color allowed to dominate a screen (the sidebar), everywhere else it's used sparingly for action.
- **Deep Indigo Hover** (`#3730a3`): hover/focus-visible state for primary actions.
- **Indigo Accent** (`#6366f1`): links, the active-nav accent bar, focus rings, and background wash on the page body (`radial-gradient` at low opacity) — a lighter, more energetic step off primary, used for emphasis rather than structure.

### Secondary
- **Slate** (`#5a6080`): secondary text-bearing surfaces and de-emphasized actions that still need to read as "a button," not a link.

### Neutral
- **Faint Indigo White** (`#f9fafc`): page background.
- **Pure Surface** (`#ffffff`): cards, modals, inputs.
- **Indigo Grey** (`#eef0f8`): muted surface fill (hover states, disabled input backgrounds).
- **Soft Indigo Line** (`#d9ddec`): the one border color used everywhere a hairline is needed.
- **Dark Indigo Ink** (`#1e2030`): primary text color — never pure black, ties body text back into the indigo family.
- **Slate Grey Text** (`#585d75`): secondary/muted text.
- **Disabled Grey** (`#9ca0b4`): disabled text and placeholder icons.

### Named Rules
**The Reserved Signal Rule.** Verdict colors (`flag` #924a0a, `human` #1a7038, `unsure` #545a78) and detector-status colors (`status-ready` #1a7038, `status-warming` #924a0a, `status-down` #b91c1c) are separate token families from each other, even where hex values coincide (human/status-ready share a green; flag/status-warming share an amber). Never write a component that reuses a verdict token to express detector status, or vice versa — a green dot on the model badge means "the service is up," a green chip on a result means "human-written," and the two claims must be free to diverge in a future color change without touching each other's code.

**The One Hue Rule.** Outside of verdict/status signal and the danger family, every color in the interface comes from the indigo hue family (primary/secondary/accent and their soft/border/hover steps). Don't introduce an unrelated hue for a new UI element just because it "needs a color" — pull from the existing indigo scale first.

## Typography

**Display/Body Font:** Figtree (self-hosted, weight range 300–900, with italics), fallback `ui-sans-serif, system-ui, sans-serif`
**Label/Mono Font:** DM Mono (self-hosted, weights 400/500), fallback `ui-monospace, SFMono-Regular, monospace`

**Character:** Figtree carries all interface prose in a clean, humanist grotesque register — confident but unadorned. DM Mono is reserved strictly for machine-readable or evidentiary facts (raw scores, model-status text, modal subtitles carrying an ID/timestamp), so a reader learns to associate the monospace register with "this number is a fact from the system," distinct from written UI copy.

### Hierarchy
- **Title** (700, 26px, 1.3 line-height): page-level `<h1>` in `PageHeader`. One per page.
- **Headline** (600, `text-lg`/18px): modal titles, section headers within a page.
- **Body** (400, `text-sm`/14px): default UI text — labels, buttons, table cells, form inputs.
- **Label** (500, `text-xs`/12px, sometimes uppercase): chip text, secondary metadata, nav sub-labels.
- **Mono/Evidentiary** (400, `text-xs`/12px, DM Mono): raw scores, timestamps, model-status badge, modal subtitles.

### Named Rules
**The Mono-For-Facts Rule.** If a piece of text is a number, timestamp, or system-reported status the instructor did not type themselves, render it in DM Mono. If it's UI copy, a label, or anything the product authored, render it in Figtree.

## Layout

Sidebar-fixed application shell: a 240px (`w-60`) fixed/sticky indigo sidebar on desktop (`md:` breakpoint, 768px), collapsing to a slide-in drawer with a floating menu button below that breakpoint. The content area is a scrollable column (`PageScroll`/`PageFill` primitives) with generous outer padding and a `PageHeader` (title + optional subtitle + right-aligned actions) at the top of every page. Content density is comfortable, not compact: cards get `p-7` (28px) internal padding, page headers use `gap-6` between title and actions.

Responsive behavior is mobile-first at the shell level (drawer nav, stacked header actions) but the working surfaces (tables, forms) are desktop-oriented — this is a tool used at a desk reviewing evidence, not a mobile-first content app.

## Elevation & Depth

Flat by default. The sidebar, nav rows, table rows, and page background carry no shadow — hierarchy there comes from color and border only (`border-border`, background-color steps). Shadow is reserved for surfaces that visually float above the workspace: result/data cards (`shadow-md`), modals (`shadow-xl`), and the mobile nav's floating open-button (`shadow-md`). Secondary buttons carry a bare `shadow-xs` as a whisper of separation from the flat page, not true elevation.

### Shadow Vocabulary
- **Card float** (`shadow-md`): result panels, the single-check form card — content that reads as "the primary artifact on this page."
- **Modal float** (`shadow-xl`): dialogs, confirmation modals — the strongest elevation in the system, reserved for content that blocks the rest of the UI.
- **Button whisper** (`shadow-xs`): secondary and destructive-outline buttons only; primary/ghost buttons carry none.

### Named Rules
**The Flat-Workspace Rule.** Structural chrome (sidebar, nav, table rows, page background) never uses `box-shadow`. If something needs to look separated from its neighbors, reach for a border or background-color step first; shadow is earned only by content that's meant to feel like a floating artifact (a card, a modal).

## Shapes

A tight two-step radius scale: `rounded-md`/`rounded-lg` (6–8px) for interactive controls — buttons, inputs, table cells, the small square icon buttons — and `rounded-xl` (12px) for card-level containers (result panels, modals, the check form). Fully round (`rounded-full`) is reserved for status dots, chips/badges, and the active-nav pill accent — anything that communicates a discrete state rather than a content boundary. No sharp corners anywhere; no radius above 12px on any container.

## Components

### Buttons
- **Shape:** `rounded-lg` (8px), five sizes from `xs` to `xl` plus dedicated `icon`/`iconSm` square variants.
- **Primary:** `bg-primary` / `text-primary-foreground`, hover to `primary-hover`, no border (transparent border kept for layout consistency with outlined variants).
- **Secondary:** `bg-surface` / `text-foreground`, `border-border`, `shadow-xs`, hovers to `surface-muted`.
- **Destructive / Destructive Outline:** solid danger fill, or danger text on a bordered surface (`border-danger/40`) for a lower-commitment destructive action.
- **Ghost:** no fill or border at rest; `muted-foreground` text, hover fills `surface-strong`.
- **Focus:** every variant defines an explicit `focus-visible:` background (never a ring) — keyboard focus reads as a slightly different hover state, not an outline.

### Chips (Verdict, Status, User-status)
- **Style:** fully round pill, `rounded-full`, colored soft-background + matching text color from that chip's dedicated token family (never a shared "success/warning/error" set).
- **State:** each verdict chip includes a small (`7px`) solid dot before the label as a redundant, non-color-dependent signal.

### Cards / Containers
- **Corner Style:** `rounded-xl` (12px).
- **Background:** `bg-surface` (pure white) against the faint-indigo page background.
- **Shadow Strategy:** `shadow-md` — see Elevation & Depth.
- **Internal Padding:** `p-7` (28px).

### Inputs / Fields
- **Style:** `rounded-md`/`rounded-lg`, `border-border`, `bg-input-bg`/`bg-surface`.
- **Focus:** background tint to `accent-soft`, plus a border-color shift to `primary` on the input-border-focus token — no glow/ring.
- **Filled vs empty:** search-style inputs shift to `modal-muted` background once they hold a value, distinguishing "has content" from "empty" without changing the border.

### Navigation
- **Style:** vertical list in the indigo sidebar, `text-primary-foreground/70` at rest, full-opacity + `font-semibold` when active, with a `3px`-wide rounded accent bar preceding the active label (not a background pill).
- **Mobile:** collapses behind a floating primary-colored square icon button (`shadow-md`) that opens a slide-in drawer with a scrim.

### Model Status Badge (signature component)
A pill (`rounded-full`, bordered, `bg-surface`) carrying a small colored status dot plus monospace status text — the one place detector-service health is shown, deliberately visually distinct from the verdict chips it sits near so the two kinds of "state" are never confused at a glance.

## Do's and Don'ts

### Do:
- **Do** render every score, timestamp, or system-reported value in DM Mono; render every authored label/copy in Figtree.
- **Do** reuse the existing indigo scale (primary/secondary/accent + soft/border/hover steps) for any new neutral or accent need before introducing a new hue.
- **Do** give verdict and detector-status their own token families even when a hex value would coincide with another family.
- **Do** use `shadow-md`/`shadow-xl` only for content that visually floats above the flat workspace (cards, modals); everything else stays flat.
- **Do** keep the radius scale to `rounded-md`/`lg` for controls, `rounded-xl` for containers, `rounded-full` for state indicators — no other radius values.

### Don't:
- **Don't** add a `box-shadow` to structural chrome (sidebar, nav rows, table rows, page background).
- **Don't** express focus state as an outline/ring; every interactive element defines an explicit `focus-visible:` background/border shift instead.
- **Don't** reuse a verdict color token to represent something that isn't a verdict, or a status color token for something that isn't detector health — keep the families semantically separate even when they visually overlap.
- **Don't** introduce a sharp (0px) or heavily rounded (>12px) corner anywhere in the system.
