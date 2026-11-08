import { describe, expect, it } from "vitest";
import { emailProblem, isSmuEmail } from "../email-domain";

describe("isSmuEmail", () => {
  it.each(["a@smu.edu.sg", "a.2024@scis.smu.edu.sg", "A@SMU.EDU.SG"])(
    "allows %s",
    (email) => expect(isSmuEmail(email)).toBe(true),
  );

  it.each([
    "a@gmail.com",
    "a@evilsmu.edu.sg",
    "a@smu.edu.sg.evil.com",
    "smu.edu.sg",
    "@smu.edu.sg",
    "a@",
  ])("refuses %s", (email) => expect(isSmuEmail(email)).toBe(false));
});

describe("emailProblem", () => {
  it.each(["annsmu.edu.sg", "@smu.edu.sg", "ann@", ""])(
    "asks for a full address for %j",
    (email) =>
      expect(emailProblem(email)).toMatch(/^Enter a full email address/),
  );

  it("names the SMU rule for a complete non-SMU address", () =>
    expect(emailProblem("ann@gmail.com")).toMatch(/^Only SMU email addresses/));

  it("passes an SMU address", () =>
    expect(emailProblem("ann@scis.smu.edu.sg")).toBeNull());
});
