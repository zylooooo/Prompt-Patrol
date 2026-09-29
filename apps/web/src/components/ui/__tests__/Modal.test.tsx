import Modal from "../Modal";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

const renderModal = (onClose: () => void) => (
  <Modal title="Rename" onClose={onClose} footer={null}>
    <input aria-label="Name" autoFocus />
  </Modal>
);

describe("Modal focus", () => {
  it("leaves an autofocused field focused, even when the parent re-renders", () => {
    // Callers pass an inline onClose, so every parent render hands in a new one.
    const { rerender } = render(renderModal(() => {}));
    expect(document.activeElement).toBe(screen.getByLabelText("Name"));

    rerender(renderModal(() => {}));
    expect(document.activeElement).toBe(screen.getByLabelText("Name"));
  });

  it("focuses the panel when nothing inside asks for focus", () => {
    render(
      <Modal title="Confirm" onClose={() => {}} footer={null}>
        <p>Sure?</p>
      </Modal>,
    );
    expect(document.activeElement).toBe(screen.getByRole("dialog"));
  });
});
