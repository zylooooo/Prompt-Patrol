import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Button, { type ButtonSize, type ButtonVariant } from "../Button";

const SIZES: ButtonSize[] = ["xs", "sm", "md", "lg", "xl", "icon", "iconSm"];
const VARIANTS: ButtonVariant[] = [
  "primary",
  "secondary",
  "destructive",
  "destructiveOutline",
  "ghost",
];

const radiusOf = (el: Element) =>
  el.className.split(/\s+/).filter((c) => c.startsWith("rounded"));

afterEach(cleanup);

describe("Button — one corner for the whole family", () => {
  it("uses the same radius at every size", () => {
    // Regression: the size map used to carry the radius, so `md` rendered
    // rounded-lg and `lg` rendered rounded-xl. The login screen and the app
    // therefore had visibly different buttons purely because they had been
    // given different sizes.
    const radii = SIZES.map((size) => {
      cleanup();
      render(<Button size={size}>x</Button>);
      return radiusOf(screen.getByRole("button")).join(" ");
    });
    expect(new Set(radii).size, `got: ${JSON.stringify(radii)}`).toBe(1);
  });

  it("uses the same radius for every variant", () => {
    const radii = VARIANTS.map((variant) => {
      cleanup();
      render(<Button variant={variant}>x</Button>);
      return radiusOf(screen.getByRole("button")).join(" ");
    });
    expect(new Set(radii).size).toBe(1);
  });

  it("carries exactly one radius class, not a stack of them", () => {
    // Two rounded-* utilities would resolve by stylesheet order, not by the
    // order written — the trap that kept the sidebar hamburger visible.
    render(<Button>x</Button>);
    expect(radiusOf(screen.getByRole("button"))).toHaveLength(1);
  });

  it("matches the control family rather than the surfaces", () => {
    // Dropdown's trigger, SearchInput and SegmentedToggle are rounded-lg;
    // cards and Modal are rounded-xl. Buttons are controls.
    render(<Button>x</Button>);
    expect(radiusOf(screen.getByRole("button"))).toEqual(["rounded-lg"]);
  });
});

describe("Button — sizing", () => {
  it("defaults to the size that lines up with the h-11 form fields", () => {
    render(<Button>x</Button>);
    const cls = screen.getByRole("button").className;
    expect(cls).toContain("px-4");
    expect(cls).toContain("py-3");
  });

  it("gives every size a distinct spacing", () => {
    const spacing = SIZES.map((size) => {
      cleanup();
      render(<Button size={size}>x</Button>);
      return screen
        .getByRole("button")
        .className.split(/\s+/)
        .filter((c) => /^(px|py|h|w)-/.test(c))
        .join(" ");
    });
    // xl differs from lg only in text size, so it is expected to collide.
    expect(new Set(spacing).size).toBeGreaterThanOrEqual(SIZES.length - 1);
  });

  it("stretches only when asked", () => {
    render(<Button fullWidth>x</Button>);
    expect(screen.getByRole("button").className).toContain("w-full");

    cleanup();
    render(<Button>x</Button>);
    expect(screen.getByRole("button").className).not.toContain("w-full");
  });
});

describe("Button — states that must not lie about interactivity", () => {
  it("gates every hover style behind :enabled", () => {
    // CSS `:hover` still matches a disabled button, so an unguarded
    // `hover:bg-*` darkened dead controls under the cursor — measured on the
    // disabled "Check answer" button before this was fixed.
    for (const variant of VARIANTS) {
      cleanup();
      render(<Button variant={variant}>x</Button>);
      const cls = screen.getByRole("button").className.split(/\s+/);
      const hover = cls.filter((c) => c.includes("hover:"));
      expect(
        hover.length,
        `${variant} has no hover style at all`,
      ).toBeGreaterThan(0);
      expect(
        hover.filter((c) => !c.startsWith("enabled:hover:")),
        `${variant} has an unguarded hover class`,
      ).toEqual([]);
    }
  });

  it("keeps the disabled affordances", () => {
    render(<Button disabled>x</Button>);
    const cls = screen.getByRole("button").className;
    expect(cls).toContain("disabled:cursor-not-allowed");
    expect(cls).toContain("disabled:opacity-60");
  });

  it("shows focus as a fill change, never a ring", () => {
    // Every variant adopts its own hover fill on keyboard focus. Rings and
    // outlines are banned app-wide — see src/__tests__/focus-indicators.test.ts.
    for (const variant of VARIANTS) {
      cleanup();
      render(<Button variant={variant}>x</Button>);
      const cls = screen.getByRole("button").className.split(/\s+/);
      expect(
        cls.filter((c) => /^focus-visible:bg-/.test(c)),
        `${variant} shows nothing on focus`,
      ).toHaveLength(1);
      expect(
        cls.filter((c) => /^focus(-visible)?:(ring|outline)-/.test(c)),
        `${variant} draws a ring`,
      ).toEqual([]);
    }
  });
});

describe("Button — behaviour", () => {
  it("hands a ref to the underlying DOM node", () => {
    // Dialogs and the drawer move focus onto a specific button; without this the
    // ref is a type error even though React 19 would pass it through.
    const ref = { current: null as HTMLButtonElement | null };
    render(<Button ref={ref}>x</Button>);
    expect(ref.current).toBe(screen.getByRole("button"));
  });

  it("defaults to type=button so it cannot submit a form by accident", () => {
    // Several of these sit inside <form>; an implicit submit would fire the
    // native POST instead of the click handler.
    render(<Button>x</Button>);
    expect(screen.getByRole("button").getAttribute("type")).toBe("button");
  });

  it("still allows an explicit submit", () => {
    render(<Button type="submit">x</Button>);
    expect(screen.getByRole("button").getAttribute("type")).toBe("submit");
  });

  it("appends a caller's className rather than replacing the base", () => {
    render(<Button className="mt-5">x</Button>);
    const cls = screen.getByRole("button").className;
    expect(cls).toContain("mt-5");
    expect(cls).toContain("rounded-lg");
  });

  it("does not fire when disabled", async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        x
      </Button>,
    );
    await userEvent.click(screen.getByRole("button"), {
      pointerEventsCheck: 0,
    });
    expect(onClick).not.toHaveBeenCalled();
  });

  it("gives each variant a distinct treatment", () => {
    const looks = VARIANTS.map((variant) => {
      cleanup();
      render(<Button variant={variant}>x</Button>);
      return screen.getByRole("button").className;
    });
    expect(new Set(looks).size).toBe(VARIANTS.length);
  });
});
