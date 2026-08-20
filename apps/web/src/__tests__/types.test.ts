import {
  atLeastRole,
  canAccess,
  canReactivate,
  displayName,
  entryId,
  isActive,
  roleLabel,
  ROLE_TEXT,
  type AppUser,
  type BatchRun,
  type SingleCheck,
  type UserRole,
} from "../types";
import { describe, expect, it } from "vitest";

/**
 * These five helpers are the most-imported code in the frontend and the whole
 * of its (cosmetic) authorization surface, so the assertions below are
 * exhaustive rather than illustrative: every role pair, and the fallback branch
 * of every function that has one.
 */

const ALL_ROLES: UserRole[] = [
  "teaching_assistant",
  "instructor",
  "root_admin",
];

const user = (over: Partial<AppUser> = {}): AppUser => ({
  id: "u1",
  email: "ada.lovelace@smu.edu.sg",
  name: "Ada Lovelace",
  role: "instructor",
  provisionedBy: null,
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  ...over,
});

describe("atLeastRole", () => {
  it("admits the full 3×3 matrix exactly as ranked", () => {
    for (let i = 0; i < ALL_ROLES.length; i++) {
      for (let j = 0; j < ALL_ROLES.length; j++) {
        expect(
          atLeastRole(ALL_ROLES[i], ALL_ROLES[j]),
          `${ALL_ROLES[i]} >= ${ALL_ROLES[j]}`,
        ).toBe(i >= j);
      }
    }
  });

  it("is reflexive — a role always satisfies its own requirement", () => {
    // Guards the `>=` in the comparison. A `>` here would lock every user out
    // of the pages gated at exactly their own role.
    for (const role of ALL_ROLES) expect(atLeastRole(role, role)).toBe(true);
  });

  it("is not symmetric — a lower rank never satisfies a higher one", () => {
    expect(atLeastRole("instructor", "root_admin")).toBe(false);
    expect(atLeastRole("teaching_assistant", "instructor")).toBe(false);
    expect(atLeastRole("teaching_assistant", "root_admin")).toBe(false);
  });

  it("is transitive", () => {
    expect(atLeastRole("root_admin", "instructor")).toBe(true);
    expect(atLeastRole("instructor", "teaching_assistant")).toBe(true);
    expect(atLeastRole("root_admin", "teaching_assistant")).toBe(true);
  });
});

describe("canAccess", () => {
  it("opens a destination to everyone when no list is given", () => {
    for (const role of ALL_ROLES) expect(canAccess(role)).toBe(true);
  });

  it("admits the listed roles and nobody else", () => {
    for (const allowed of ALL_ROLES) {
      for (const role of ALL_ROLES) {
        expect(canAccess(role, [allowed]), `${role} in [${allowed}]`).toBe(
          role === allowed,
        );
      }
    }
  });

  it("does not let seniority substitute for membership", () => {
    // The whole reason this exists beside atLeastRole. "Manage My Assistants"
    // is instructor work, and an admin outranking an instructor must not reach
    // it - no assistant is ever supervised by an admin.
    expect(canAccess("root_admin", ["instructor"])).toBe(false);
    expect(canAccess("instructor", ["instructor"])).toBe(true);
  });

  it("admits any member of a multi-role list", () => {
    const allowed: UserRole[] = ["instructor", "root_admin"];
    expect(canAccess("instructor", allowed)).toBe(true);
    expect(canAccess("root_admin", allowed)).toBe(true);
    expect(canAccess("teaching_assistant", allowed)).toBe(false);
  });

  it("admits nobody when the list is empty", () => {
    // Distinct from omitting it, which admits everyone.
    for (const role of ALL_ROLES) expect(canAccess(role, [])).toBe(false);
  });
});

describe("isActive", () => {
  it("is true only for the active status", () => {
    expect(isActive(user())).toBe(true);
    expect(isActive(user({ status: "deactivated" }))).toBe(false);
    expect(isActive(user({ status: "deleted" }))).toBe(false);
  });

  it("excludes deleted users, so selectors cannot offer them", () => {
    // Both non-active states fail the check. A deleted user must never be
    // selectable for a new assignment, and neither must a deactivated one.
    expect(isActive(user({ status: "deleted" }))).toBe(false);
  });
});

describe("canReactivate", () => {
  it("is true only for a deactivated user", () => {
    // Deletion is terminal: re-granting access means provisioning a fresh
    // account, not reviving a removed one.
    expect(canReactivate(user({ status: "deactivated" }))).toBe(true);
    expect(canReactivate(user({ status: "active" }))).toBe(false);
    expect(canReactivate(user({ status: "deleted" }))).toBe(false);
  });
});

describe("displayName", () => {
  it("prefers the name (positive control)", () => {
    expect(displayName(user())).toBe("Ada Lovelace");
  });

  it("falls back to the email local part when name is null", () => {
    expect(displayName(user({ name: null }))).toBe("ada.lovelace");
  });

  it("treats an empty-string name as a name, not as missing", () => {
    // `??` only falls through on null/undefined. Documenting the behaviour so a
    // switch to `||` is a deliberate change rather than an accident — it would
    // render blank cells in every table that shows a name.
    expect(displayName(user({ name: "" }))).toBe("");
  });

  it("takes the first segment of an email containing several @", () => {
    expect(displayName(user({ name: null, email: "a@b@smu.edu.sg" }))).toBe(
      "a",
    );
  });

  it("returns the whole string when the email has no @ at all", () => {
    expect(displayName(user({ name: null, email: "malformed" }))).toBe(
      "malformed",
    );
  });

  it("returns an empty string for an empty email rather than throwing", () => {
    expect(displayName(user({ name: null, email: "" }))).toBe("");
  });
});

describe("roleLabel", () => {
  it("maps every role to a non-empty label, with no gaps", () => {
    for (const role of ALL_ROLES) {
      const label = roleLabel(user({ role }));
      expect(label, role).toBeTruthy();
      expect(label, role).toBe(ROLE_TEXT[role]);
    }
  });

  it("covers exactly the declared roles — no extras, none missing", () => {
    expect(Object.keys(ROLE_TEXT).sort()).toEqual([...ALL_ROLES].sort());
  });
});

describe("entryId", () => {
  // History routing depends on this discriminating correctly: a batch is keyed
  // by `id`, a single check by `checkId`, and both feed /history/:id.
  it("uses checkId for a single check", () => {
    expect(entryId({ kind: "single", checkId: "c1" } as SingleCheck)).toBe(
      "c1",
    );
  });

  it("prefers id over a stray checkId on a batch", () => {
    const batch = {
      kind: "batch",
      id: "b1",
      checkId: "should-be-ignored",
    } as unknown as BatchRun;
    expect(entryId(batch)).toBe("b1");
  });

  it("keeps the two kinds distinguishable when the ids collide", () => {
    // Same underlying id string in both shapes must still route to the entry
    // the caller meant, so the discriminant — not the value — has to decide.
    const single = { kind: "single", checkId: "x" } as SingleCheck;
    const batch = { kind: "batch", id: "x" } as unknown as BatchRun;
    expect(entryId(single)).toBe(entryId(batch));
  });
});
