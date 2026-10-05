import { describe, expect, it } from "vitest";
import { initialOf } from "./accountModel";

describe("the user chip", () => {
  it("shows a name's first letter on the avatar, and a mark for none", () => {
    expect(initialOf("ada lovelace")).toBe("A");
    expect(initialOf("  owner@example.test")).toBe("O");
    expect(initialOf("")).toBe("?");
  });
});
