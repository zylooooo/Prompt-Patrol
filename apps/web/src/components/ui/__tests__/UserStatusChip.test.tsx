import UserStatusChip from "../UserStatusChip";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  USER_STATUS_TEXT,
  type AppUser,
  type UserStatus,
} from "../../../types";

const STATUSES = Object.keys(USER_STATUS_TEXT) as UserStatus[];

const user = (over: Partial<AppUser>): AppUser => ({
  id: "1",
  email: "a@b.co",
  name: null,
  role: "teaching_assistant",
  status: "active",
  supervisorIds: [],
  createdAt: "2026-07-01T00:00:00.000Z",
  firstLoginAt: "2026-07-02T00:00:00.000Z",
  ...over,
});

afterEach(cleanup);

describe("UserStatusChip", () => {
  it.each(STATUSES)("labels %s with its own wording", (status) => {
    render(<UserStatusChip user={user({ status })} />);

    expect(screen.getByText(USER_STATUS_TEXT[status])).toBeDefined();
  });

  it("never falls back to another state's label", () => {
    render(<UserStatusChip user={user({ status: "deleted" })} />);

    expect(screen.queryByText("Deactivated")).toBeNull();
  });

  it("says Pending for an active account that never signed in", () => {
    render(<UserStatusChip user={user({ firstLoginAt: null })} />);
    expect(screen.getByText("Pending")).toBeTruthy();
  });

  it("says Active once they have signed in", () => {
    render(<UserStatusChip user={user({})} />);
    expect(screen.getByText("Active")).toBeTruthy();
  });

  it("lets deactivated and deleted win over pending", () => {
    render(
      <UserStatusChip
        user={user({ status: "deactivated", firstLoginAt: null })}
      />,
    );
    expect(screen.getByText("Deactivated")).toBeTruthy();
  });
});
