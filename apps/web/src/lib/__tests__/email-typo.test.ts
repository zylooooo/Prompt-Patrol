import { describe, expect, it } from "vitest";
import { suggestEmailDomain } from "../email-typo";

describe("suggestEmailDomain", () => {
  it("corrects a near miss of smu.edu.sg", () => {
    expect(suggestEmailDomain("ann@smu.edu.s")).toBe("ann@smu.edu.sg");
    expect(suggestEmailDomain("ann@smu.edu.sgg")).toBe("ann@smu.edu.sg");
  });

  it("leaves correct, unrelated and malformed addresses alone", () => {
    expect(suggestEmailDomain("ann@smu.edu.sg")).toBeNull();
    expect(suggestEmailDomain("ann@gmial.com")).toBeNull();
    expect(suggestEmailDomain("ann@scis.smu.edu.sg")).toBeNull();
    expect(suggestEmailDomain("ann@example.org")).toBeNull();
    expect(suggestEmailDomain("not-an-email")).toBeNull();
    expect(suggestEmailDomain("")).toBeNull();
  });

  it("is case-insensitive on the domain and keeps the local part as typed", () => {
    expect(suggestEmailDomain("Ann.Lee@SMU.EDU.S")).toBe("Ann.Lee@smu.edu.sg");
  });

  it("leaves other real Singapore university domains alone", () => {
    for (const d of [
      "ntu.edu.sg",
      "sit.edu.sg",
      "sutd.edu.sg",
      "nus.edu.sg",
      "u.nus.edu",
      "suss.edu.sg",
    ]) {
      expect(suggestEmailDomain(`ann@${d}`)).toBeNull();
    }
  });
});
