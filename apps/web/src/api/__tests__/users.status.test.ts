import {
  deleteUser,
  listMyAssistants,
  listUsers,
  setUserActive,
} from "../stub";
import type { User } from "../auth";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const USERS_V2 = "pp.users.v2";
const USERS_V3 = "pp.users.v3";

const ADMIN: User = { email: "admin@example.com", role: "root_admin" };
const INSTRUCTOR_A: User = {
  email: "instructor.a@example.com",
  role: "instructor",
};

// The shape this stub persisted before accounts gained a lifecycle status.
const LEGACY_ROW = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "admin@example.com",
  name: "Demo Admin",
  role: "root_admin",
  provisionedBy: null,
  deletedAt: null,
  createdAt: "2026-07-01T09:00:00.000Z",
};

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("persisted accounts", () => {
  it("gives every seeded account a status", async () => {
    const users = await listUsers(ADMIN);

    expect(users.length).toBeGreaterThan(0);
    for (const user of users) expect(user.status).toBeDefined();
  });

  it("discards rows written before the status field existed", async () => {
    localStorage.setItem(USERS_V2, JSON.stringify([LEGACY_ROW]));

    const users = await listUsers(ADMIN);

    for (const user of users) expect(user.status).toBeDefined();
    expect(localStorage.getItem(USERS_V2)).toBeNull();
    expect(localStorage.getItem(USERS_V3)).not.toBeNull();
  });

  it("leaves rows already written under the current key alone", async () => {
    const before = await listUsers(ADMIN);
    await setUserActive(ADMIN, before[1].id, false);

    const after = await listUsers(ADMIN);

    expect(after.find((u) => u.id === before[1].id)?.status).toBe(
      "deactivated",
    );
  });
});

describe("listMyAssistants", () => {
  it("drops assistants whose account was deleted", async () => {
    const before = await listMyAssistants(INSTRUCTOR_A);
    const target = before[0];
    expect(target).toBeDefined();

    await deleteUser(ADMIN, target.id);

    const after = await listMyAssistants(INSTRUCTOR_A);
    expect(after.map((ta) => ta.id)).not.toContain(target.id);
  });

  it("keeps assistants who were only deactivated", async () => {
    const before = await listMyAssistants(INSTRUCTOR_A);
    const target = before[0];

    await setUserActive(ADMIN, target.id, false);

    const after = await listMyAssistants(INSTRUCTOR_A);
    expect(after.find((ta) => ta.id === target.id)?.status).toBe("deactivated");
  });
});
