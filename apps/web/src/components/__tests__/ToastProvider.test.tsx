import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ToastProvider } from "../ToastProvider";
import { useToast, type ToastOptions } from "../../hooks/useToast";

function Trigger({ message, options }: { message: string; options?: ToastOptions }) {
  const { showToast } = useToast();
  return <button onClick={() => showToast(message, options)}>show</button>;
}

function renderToast(message: string, options?: ToastOptions) {
  render(
    <ToastProvider>
      <Trigger message={message} options={options} />
    </ToastProvider>,
  );
  fireEvent.click(screen.getByText("show"));
}

afterEach(cleanup);

describe("ToastProvider", () => {
  it("runs the action once and dismisses the toast", () => {
    const onClick = vi.fn();
    renderToast("Sam deactivated", { action: { label: "Undo", onClick } });

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));

    expect(onClick).toHaveBeenCalledOnce();
    expect(screen.queryByText("Sam deactivated")).toBeNull();
  });

  it("announces an error assertively", () => {
    renderToast("Couldn't delete Sam. Try again.", { tone: "error" });

    expect(screen.getByRole("alert").textContent).toContain("Couldn't delete Sam");
  });

  it("dismisses from the close button", () => {
    renderToast("Saved");

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByText("Saved")).toBeNull();
  });
});
