import {
  clearPreviousUserData,
  clearSignedOutState,
  LOGIN_HINT_KEY,
} from "../auth";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const STUB_KEYS = [
  "pp.history.v2",
  "pp.users.v3",
  "pp.users.v2",
  "pp.supervision.v2",
  "pp.history.seeded.v2",
];

const seedEverything = () => {
  for (const key of STUB_KEYS) localStorage.setItem(key, '["something"]');
  localStorage.setItem(LOGIN_HINT_KEY, "ada@smu.edu.sg");
};

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("clearSignedOutState", () => {
  it("removes every key the app owns", () => {
    seedEverything();

    clearSignedOutState();

    for (const key of [...STUB_KEYS, LOGIN_HINT_KEY]) {
      expect(localStorage.getItem(key)).toBeNull();
    }
  });

  it("leaves storage belonging to anything else alone", () => {
    seedEverything();
    localStorage.setItem("unrelated-key", "keep me");

    clearSignedOutState();

    expect(localStorage.getItem("unrelated-key")).toBe("keep me");
  });

  it("is safe to call when there is nothing stored", () => {
    expect(() => clearSignedOutState()).not.toThrow();
  });
});

describe("clearPreviousUserData", () => {
  it("drops the previous user's data but not the hint being rewritten", () => {
    seedEverything();

    clearPreviousUserData();

    for (const key of STUB_KEYS) expect(localStorage.getItem(key)).toBeNull();
    expect(localStorage.getItem(LOGIN_HINT_KEY)).toBe("ada@smu.edu.sg");
  });
});
