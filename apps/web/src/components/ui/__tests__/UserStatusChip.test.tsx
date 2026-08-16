import UserStatusChip from "../UserStatusChip";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { USER_STATUS_TEXT, type UserStatus } from "../../../types";

const STATUSES = Object.keys(USER_STATUS_TEXT) as UserStatus[];

afterEach(cleanup);

describe("UserStatusChip", () => {
  it.each(STATUSES)("labels %s with its own wording", (status) => {
    render(<UserStatusChip status={status} />);

    expect(screen.getByText(USER_STATUS_TEXT[status])).toBeDefined();
  });

  it("never falls back to another state's label", () => {
    render(<UserStatusChip status="deleted" />);

    expect(screen.queryByText("Deactivated")).toBeNull();
  });
});
