import cssSource from "../index.css?raw";
import { describe, expect, it } from "vitest";

/**
 * Focus is shown by a **fill change**, never by a ring or an outline.
 *
 * A focused control adopts a different background — buttons take their hover fill,
 * text fields take a light indigo tint, sidebar rows lighten. Nothing is drawn
 * *around* a control, which was the look being avoided.
 *
 * Two halves have to hold together, so this test guards both:
 *
 *  1. no component may draw a ring or outline on focus, and
 *  2. every interactive component must declare *some* focus style.
 *
 * Without (2) the first half is trivially satisfiable by deleting all focus styling,
 * which is how this file started life — and that is a WCAG 2.4.7 failure. Without (1)
 * the rings creep back.
 *
 * Sources are read through Vite's raw glob rather than `node:fs` — `src/` is typed
 * for the browser, and a test reaching for Node APIs would force Node types into the
 * app tsconfig.
 */

const MODULES = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

const SOURCES = Object.entries(MODULES).filter(
  ([path]) => !path.includes("__tests__"),
);

const FOCUS_RING = /\b(?:focus|focus-visible|focus-within):ring-[\w./[\]-]+/g;
const FOCUS_OUTLINE =
  /\b(?:focus|focus-visible|focus-within):outline-(?!hidden\b|none\b)[\w./[\]-]+/g;
// A fill change: background, text colour or underline, on focus.
const FOCUS_FILL =
  /\b(?:focus-visible|focus-within):(?:bg-|text-|underline)[\w./[\]-]*/g;

/** Every module that renders something a user can focus. */
const INTERACTIVE = [
  "components/ui/Button.tsx",
  "components/ui/Dropdown.tsx",
  "components/ui/Pagination.tsx",
  "components/ui/RowAction.tsx",
  "components/ui/SearchInput.tsx",
  "components/ui/SegmentedToggle.tsx",
  "components/ui/Tabs.tsx",
  "components/ui/TextButton.tsx",
  "components/ui/TokenMultiSelect.tsx",
  "components/ui/DataTable.tsx",
  "components/Sidebar.tsx",
  "components/ToastProvider.tsx",
  "components/DeactivateInstructorDialog.tsx",
  "components/SingleCheckTab.tsx",
  "pages/LoginPage.tsx",
  "pages/UsersPage.tsx",
  "pages/TeachingAssistantsPage.tsx",
];

const scan = (pattern: RegExp): string[] =>
  SOURCES.flatMap(([path, code]) =>
    (String(code).match(pattern) ?? []).map((hit) => `${path}: ${hit}`),
  );

describe("focus is never drawn as a ring or an outline", () => {
  it("finds source files to scan (guards against a vacuous pass)", () => {
    expect(SOURCES.length).toBeGreaterThan(30);
  });

  it("declares no focus ring on any component", () => {
    expect(scan(FOCUS_RING)).toEqual([]);
  });

  it("declares no focus outline on any component", () => {
    // `focus:outline-hidden`/`-none` would be redundant rather than wrong, so they
    // are excluded — anything that *draws* an outline is not.
    expect(scan(FOCUS_OUTLINE)).toEqual([]);
  });

  it("kills the browser's own outline in the base layer", () => {
    // Without this the UA outline replaces the ring we removed, and the fill change
    // is not the only thing on screen.
    const base = cssSource.slice(cssSource.indexOf("@layer base"));
    expect(base).toMatch(
      /:focus,\s*\n?\s*:focus-visible\s*{\s*outline:\s*none;/,
    );
  });
});

describe("but focus is always visible", () => {
  it("gives every interactive component a focus fill", () => {
    // The half that stops "no rings" from being satisfied by showing nothing at all.
    const missing = INTERACTIVE.filter((rel) => {
      const entry = SOURCES.find(([path]) => path.endsWith(rel));
      if (!entry) throw new Error(`${rel} is listed but was not found on disk`);
      return (String(entry[1]).match(FOCUS_FILL) ?? []).length === 0;
    });
    expect(missing, "these render focusable things but show nothing on focus").toEqual(
      [],
    );
  });

  it("covers every ui/ primitive that renders a <button> or an <input>", () => {
    // Catches a *new* primitive added without a focus style — the list above cannot
    // go stale silently.
    const unlisted = SOURCES.filter(([path, code]) => {
      if (!path.includes("/components/ui/")) return false;
      const src = String(code);
      if (!/<(?:button|input|textarea)\b/.test(src)) return false;
      return (
        !INTERACTIVE.some((rel) => path.endsWith(rel)) &&
        (src.match(FOCUS_FILL) ?? []).length === 0
      );
    }).map(([path]) => path);
    expect(unlisted).toEqual([]);
  });
});
