import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import TextButton, { TextLink, type TextTone } from "../TextButton";

const TONES: TextTone[] = ["primary", "muted"];

afterEach(cleanup);

describe("TextButton", () => {
  it("renders the button and the link identically for each tone", () => {
    // Same reason as RowAction: one look for a text action, whichever element.
    for (const tone of TONES) {
      cleanup();
      render(
        <MemoryRouter>
          <TextButton tone={tone} onClick={() => {}}>
            a
          </TextButton>
          <TextLink tone={tone} to="/x">
            b
          </TextLink>
        </MemoryRouter>,
      );
      expect(screen.getByRole("link").className).toBe(
        screen.getByRole("button").className,
      );
    }
  });

  it("shows focus as an underline, matching its hover", () => {
    render(<TextButton onClick={() => {}}>a</TextButton>);
    const cls = screen.getByRole("button").className.split(/\s+/);
    expect(cls).toContain("hover:underline");
    expect(cls).toContain("focus-visible:underline");
  });

  it("defaults to type=button so it cannot submit a surrounding form", () => {
    render(<TextButton onClick={() => {}}>a</TextButton>);
    expect(screen.getByRole("button").getAttribute("type")).toBe("button");
  });

  it("appends a caller's className rather than replacing the base", () => {
    render(
      <TextButton onClick={() => {}} className="mt-2">
        a
      </TextButton>,
    );
    const cls = screen.getByRole("button").className;
    expect(cls).toContain("mt-2");
    expect(cls).toContain("text-primary");
  });

  it("fires onClick", async () => {
    const onClick = vi.fn();
    render(<TextButton onClick={onClick}>a</TextButton>);
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
