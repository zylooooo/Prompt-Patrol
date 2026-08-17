import type { User } from "../auth";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createAccount, deleteUser, listUsers, setUserActive } from "../users";

/**
 * These cover the seams between the two shapes, which are the parts that fail
 * quietly rather than loudly: a roster that drops every removed account, a
 * second page nobody asked for, a field that arrives under a different name and
 * renders as blank.
 */

const ADMIN: User = {
  email: "admin@smu.edu.sg",
  role: "root_admin",
  provisionedBy: null,
};

const ME = {
  id: "id-admin",
  email: "admin@smu.edu.sg",
  display_name: "Demo Admin",
  role: "root_admin",
  status: "active",
  provisioned_by: null,
  created_at: "2026-07-01T00:00:00.000Z",
};

const row = (id: string, over: Record<string, unknown> = {}) => ({
  ...ME,
  id,
  email: `${id}@smu.edu.sg`,
  role: "teaching_assistant",
  ...over,
});

/** Answers each call from `handler`, keyed off the requested path. */
function route(handler: (url: string, init?: RequestInit) => unknown) {
  const mock = vi.fn((url: string, init?: RequestInit) =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(handler(url, init)),
    }),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

const requested = (mock: ReturnType<typeof route>) =>
  mock.mock.calls.map((call) => call[0]).filter((url) => !url.includes("/me"));

const paramsOf = (url: string) => new URLSearchParams(url.split("?")[1] ?? "");

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("listUsers", () => {
  it("asks for removed accounts, not just the active ones", async () => {
    // The endpoint defaults to active only. Take the default and every
    // deactivated and deleted row silently leaves the administrative roster -
    // the one screen whose whole job is showing them.
    const mock = route((url) =>
      url.includes("/me") ? ME : { items: [], next_cursor: null },
    );

    await listUsers(ADMIN);

    expect(paramsOf(requested(mock)[0]).getAll("status")).toEqual([
      "active",
      "deactivated",
      "deleted",
    ]);
  });

  it("addresses the collection on its trailing slash", async () => {
    // FastAPI answers /api/users with a 307 to /api/users/.
    const mock = route((url) =>
      url.includes("/me") ? ME : { items: [], next_cursor: null },
    );

    await listUsers(ADMIN);

    expect(requested(mock)[0].startsWith("/api/users/?")).toBe(true);
  });

  it("follows the cursor instead of showing the first page as the whole list", async () => {
    let page = 0;
    const mock = route((url) => {
      if (url.includes("/me")) return ME;
      page += 1;
      return page === 1
        ? { items: [row("first")], next_cursor: "cursor-2" }
        : { items: [row("second")], next_cursor: null };
    });

    const users = await listUsers(ADMIN);

    expect(users.map((user) => user.id)).toEqual(["first", "second"]);
    expect(paramsOf(requested(mock)[1]).get("cursor")).toBe("cursor-2");
  });

  it("reads the server's field names onto the ones the screens use", async () => {
    route((url) =>
      url.includes("/me")
        ? ME
        : {
            items: [
              row("ta-1", {
                display_name: "Ada",
                provisioned_by: "id-admin",
                status: "deactivated",
              }),
            ],
            next_cursor: null,
          },
    );

    const [user] = await listUsers(ADMIN);

    expect(user).toEqual({
      id: "ta-1",
      email: "ta-1@smu.edu.sg",
      name: "Ada",
      role: "teaching_assistant",
      status: "deactivated",
      provisionedBy: "id-admin",
      createdAt: "2026-07-01T00:00:00.000Z",
    });
  });
});

describe("setUserActive", () => {
  it("posts to reactivate when switching an account back on", async () => {
    const mock = route(() => row("ta-1", { status: "active" }));

    await setUserActive(ADMIN, "ta-1", true);

    expect(mock.mock.calls[0][0]).toBe("/api/users/ta-1/reactivate");
    expect(mock.mock.calls[0][1]).toMatchObject({ method: "POST" });
  });

  it("posts to deactivate when switching it off", async () => {
    const mock = route(() => row("ta-1", { status: "deactivated" }));

    const user = await setUserActive(ADMIN, "ta-1", false);

    expect(mock.mock.calls[0][0]).toBe("/api/users/ta-1/deactivate");
    expect(user.status).toBe("deactivated");
  });
});

describe("deleteUser", () => {
  it("returns the removed row rather than assuming it worked", async () => {
    const mock = route(() => row("ta-1", { status: "deleted" }));

    const user = await deleteUser(ADMIN, "ta-1");

    expect(mock.mock.calls[0][1]).toMatchObject({ method: "DELETE" });
    expect(user.status).toBe("deleted");
  });
});

describe("createAccount", () => {
  it("sends the display name under the name the API gives it", async () => {
    const mock = route(() => row("ta-1", { display_name: "Ada" }));

    await createAccount(ADMIN, {
      email: "ada@smu.edu.sg",
      role: "teaching_assistant",
      name: "  Ada  ",
      supervisorIds: [],
    });

    expect(JSON.parse(mock.mock.calls[0][1]?.body as string)).toEqual({
      email: "ada@smu.edu.sg",
      role: "teaching_assistant",
      display_name: "Ada",
    });
  });

  it("lets any domain through to the server", async () => {
    // Deliberate. Whose addresses are acceptable is a deployment question and
    // this layer no longer answers it; when it becomes a rule it becomes one
    // server-side, where it cannot be skipped.
    const mock = route(() => row("ta-1", { email: "ada@gmail.com" }));

    const created = await createAccount(ADMIN, {
      email: "ada@gmail.com",
      role: "teaching_assistant",
    });

    expect(mock).toHaveBeenCalledOnce();
    expect(created.email).toBe("ada@gmail.com");
  });
});
