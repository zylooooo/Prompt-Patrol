import cssSource from "../index.css?raw";
import { describe, expect, it } from "vitest";

/**
 * Colour may only come from the `@theme` block in `index.css`.
 *
 * `--color-*: initial` already makes a raw palette class generate no CSS, so a
 * bypass renders visibly wrong rather than quietly off-palette. This test is the
 * faster feedback loop: it names the file and the class instead of leaving
 * someone to notice an unstyled box.
 *
 * Sources are read through Vite's raw glob rather than `node:fs` — `src/` is
 * typed for the browser, and a test reaching for Node APIs would force Node
 * types into the app tsconfig.
 */

const MODULES = import.meta.glob("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

const SOURCES = Object.entries(MODULES).filter(
  ([path]) => !path.includes("__tests__"),
);

const PALETTE = [
  "slate",
  "gray",
  "grey",
  "zinc",
  "neutral",
  "stone",
  "red",
  "orange",
  "amber",
  "yellow",
  "lime",
  "green",
  "emerald",
  "teal",
  "cyan",
  "sky",
  "blue",
  "indigo",
  "violet",
  "purple",
  "fuchsia",
  "pink",
  "rose",
].join("|");

const PROPS =
  "bg|text|border|ring|fill|stroke|from|via|to|outline|decoration|accent|caret|divide|shadow|placeholder";

const RAW_PALETTE = new RegExp(
  `\\b(?:${PROPS})-(?:${PALETTE})-\\d{2,3}\\b`,
  "g",
);
const RAW_KEYWORD = new RegExp(`\\b(?:${PROPS})-(?:white|black)\\b`, "g");
const ARBITRARY = new RegExp(
  `\\b(?:${PROPS})-\\[(?:#|rgba?\\(|hsla?\\(|oklch\\()`,
  "g",
);

const scan = (pattern: RegExp): string[] =>
  SOURCES.flatMap(([path, code]) =>
    (code.match(pattern) ?? []).map((hit) => `${path}: ${hit}`),
  );

describe("colour comes only from the design tokens", () => {
  it("finds source files to scan (guards against a vacuous pass)", () => {
    expect(SOURCES.length).toBeGreaterThan(30);
  });

  it("uses no raw Tailwind palette class", () => {
    // e.g. `bg-amber-50` — the dev-login panel carried two of these until the
    // default palette was cleared out of the theme.
    expect(scan(RAW_PALETTE)).toEqual([]);
  });

  it("uses no bare white/black", () => {
    // `text-white` is a colour decision that belongs in a token, usually a
    // `*-foreground`.
    expect(scan(RAW_KEYWORD)).toEqual([]);
  });

  it("uses no arbitrary colour value", () => {
    // `bg-[#fff]` is a token by another name, and an untracked one.
    expect(scan(ARBITRARY)).toEqual([]);
  });
});

describe("the theme is the whole colour vocabulary", () => {
  it("clears Tailwind's default palette", () => {
    // What makes a bypass fail loudly rather than resolve to an off-palette
    // colour that merely looks slightly wrong.
    expect(cssSource).toContain("--color-*: initial");
  });

  it("keeps transparent and current, which are keywords rather than colours", () => {
    // `border-transparent` and `text-current` are structural; clearing the
    // palette without re-declaring these breaks Button, Tabs and Sidebar.
    expect(cssSource).toContain("--color-transparent: transparent");
    expect(cssSource).toContain("--color-current: currentColor");
  });

  it("declares every colour as a hex token", () => {
    const tokens = [...cssSource.matchAll(/--color-([a-z-]+):\s*([^;]+);/g)]
      .filter(([, name]) => name !== "transparent" && name !== "current")
      .map(([, name, value]) => ({ name, value: value.trim() }));

    expect(tokens.length).toBeGreaterThan(25);
    for (const { name, value } of tokens) {
      expect(value, `--color-${name}`).toMatch(/^#[0-9a-fA-F]{3,8}$/);
    }
  });
});
