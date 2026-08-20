import {
  createAccount,
  deactivateInstructor,
  deleteUser,
  listMyAssistants,
  listUsers,
  setSupervisor,
  setUserActive,
} from "../users";
import type { User } from "../auth";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
    });

    expect(JSON.parse(mock.mock.calls[0][1]?.body as string)).toEqual({
      email: "ada@smu.edu.sg",
      role: "teaching_assistant",
      display_name: "Ada",
      supervisor_id: null,
    });
  });

  it("sends the chosen supervisor to the server", async () => {
    // This is the whole point: the picked instructor used to be written to
    // localStorage and never left the browser, so the database recorded whoever
    // pressed the button as the supervisor.
    const mock = route(() => row("ta-1", { provisioned_by: "id-teach" }));

    const created = await createAccount(ADMIN, {
      email: "ada@smu.edu.sg",
      role: "teaching_assistant",
      supervisorId: "id-teach",
    });

    expect(JSON.parse(mock.mock.calls[0][1]?.body as string)).toMatchObject({
      supervisor_id: "id-teach",
    });
    expect(created.provisionedBy).toBe("id-teach");
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

describe("setSupervisor", () => {
  it("posts the new supervisor to the assistant's own route", async () => {
    const mock = route(() => row("ta-1", { provisioned_by: "id-teach" }));

    const user = await setSupervisor(ADMIN, "ta-1", "id-teach");

    expect(mock.mock.calls[0][0]).toBe("/api/users/ta-1/supervisor");
    expect(mock.mock.calls[0][1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(mock.mock.calls[0][1]?.body as string)).toEqual({
      supervisor_id: "id-teach",
    });
    expect(user.provisionedBy).toBe("id-teach");
  });

  it("sends null to unassign rather than omitting the field", async () => {
    // Omitted and null mean the same thing to the schema, but only null says it
    // on purpose - and the caller is asking for a change, not a default.
    const mock = route(() => row("ta-1", { provisioned_by: null }));

    const user = await setSupervisor(ADMIN, "ta-1", null);

    expect(JSON.parse(mock.mock.calls[0][1]?.body as string)).toEqual({
      supervisor_id: null,
    });
    expect(user.provisionedBy).toBeNull();
  });
});

describe("listMyAssistants", () => {
  it("takes an instructor's list as the server scoped it", async () => {
    // The endpoint already narrows an instructor to the assistants they
    // supervise, so filtering again here could only ever remove somebody the
    // server said belongs.
    route(() => ({
      items: [row("ta-1"), row("ta-2")],
      next_cursor: null,
    }));

    const mine = await listMyAssistants({ ...ADMIN, role: "instructor" });

    expect(mine.map((ta) => ta.id)).toEqual(["ta-1", "ta-2"]);
  });

  it("asks only for assistants that are still assignable", async () => {
    // Deleted assistants are gone; deactivated ones are still yours and still
    // reactivatable, so both live statuses are requested and nothing else.
    const mock = route(() => ({ items: [], next_cursor: null }));

    await listMyAssistants({ ...ADMIN, role: "instructor" });

    const params = paramsOf(requested(mock)[0]);
    expect(params.get("role")).toBe("teaching_assistant");
    expect(params.getAll("status")).toEqual(["active", "deactivated"]);
  });

  it("does not read the profile to decide whose assistants these are", async () => {
    // This page belongs to instructors alone. It used to fall back to "the
    // assistants whose provisioned_by is me", which for an admin described a
    // supervision edge the server refuses to create - a supervisor must be an
    // instructor. Reintroducing that read would reintroduce the idea.
    const mock = route(() => ({ items: [row("ta-1")], next_cursor: null }));

    await listMyAssistants({ ...ADMIN, role: "instructor" });

    expect(
      mock.mock.calls.filter((call) => call[0].includes("/me")),
    ).toHaveLength(0);
  });
});

describe("deactivateInstructor", () => {
  const assistantsThenTransitions = (provisionedBy: string) =>
    route((url) => {
      if (url.includes("/me")) return ME;
      if (url.startsWith("/api/users/?")) {
        return {
          items: [
            row("ta-1", { provisioned_by: provisionedBy }),
            row("ta-2", { provisioned_by: "id-other-teacher" }),
          ],
          next_cursor: null,
        };
      }
      return row("id-teach", { status: "deactivated" });
    });

  it("moves only the assistants this instructor supervises", async () => {
    const mock = assistantsThenTransitions("id-teach");

    const outcome = await deactivateInstructor(ADMIN, "id-teach", {
      mode: "reassign",
      toId: "id-replacement",
    });

    expect(outcome.reassigned).toBe(1);
    expect(requested(mock)).toContain("/api/users/ta-1/supervisor");
    expect(requested(mock)).not.toContain("/api/users/ta-2/supervisor");
  });

  it("settles the assistants before switching the instructor off", async () => {
    // If a reassignment fails the instructor is still active, so the admin can
    // retry from a state they recognise instead of a half-applied one.
    const mock = assistantsThenTransitions("id-teach");

    await deactivateInstructor(ADMIN, "id-teach", {
      mode: "reassign",
      toId: "id-replacement",
    });

    const calls = requested(mock);
    expect(calls.indexOf("/api/users/ta-1/supervisor")).toBeLessThan(
      calls.indexOf("/api/users/id-teach/deactivate"),
    );
  });

  it("unassigns them when that is the chosen plan", async () => {
    const mock = assistantsThenTransitions("id-teach");

    const outcome = await deactivateInstructor(ADMIN, "id-teach", {
      mode: "leave",
    });

    expect(outcome.leftUnassigned).toBe(1);
    const body = mock.mock.calls.find((call) =>
      call[0].includes("/ta-1/supervisor"),
    )?.[1]?.body as string;
    expect(JSON.parse(body)).toEqual({ supervisor_id: null });
  });

  it("deactivates them without touching their supervisor", async () => {
    // The edge is kept deliberately: reactivating the instructor brings the team
    // back rather than leaving an admin to rebuild it.
    const mock = assistantsThenTransitions("id-teach");

    const outcome = await deactivateInstructor(ADMIN, "id-teach", {
      mode: "deactivate",
    });

    expect(outcome.deactivated).toBe(1);
    expect(requested(mock)).toContain("/api/users/ta-1/deactivate");
    expect(requested(mock)).not.toContain("/api/users/ta-1/supervisor");
  });
});
