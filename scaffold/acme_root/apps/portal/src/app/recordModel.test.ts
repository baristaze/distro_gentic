import { describe, expect, it } from "vitest";
import { costLine, countLine, microsOf, personName } from "./recordModel";

const users = [
  { id: "u1", display_name: "Ada", email: "ada@example.test" },
  { id: "u2", display_name: " ", email: "bo@example.test" },
];

describe("personName", () => {
  it("names a member by name, else by address", () => {
    expect(personName(users, "u1")).toBe("Ada");
    expect(personName(users, "u2")).toBe("bo@example.test");
  });
  it("never shows an id for one it cannot name", () => {
    expect(personName(users, "u9")).toBe("a former member");
    expect(personName(undefined, "u1")).toBe("a former member");
    expect(personName(users, null)).toBe("no one");
  });
});

describe("costLine", () => {
  it("shows two places, and more for an amount below a cent", () => {
    expect(costLine(0)).toBe("0.00");
    expect(costLine(1_500_000)).toBe("1.50");
    expect(costLine(2_500)).toBe("0.0025");
  });
});

describe("microsOf", () => {
  it("reads a positive amount to the millionth", () => {
    expect(microsOf("1.5")).toBe(1_500_000);
    expect(microsOf(" 2 ")).toBe(2_000_000);
    expect(microsOf("0.000001")).toBe(1);
  });
  it("refuses anything else", () => {
    for (const text of ["", "0", "-1", "1.0000001", "1e3", "abc", "1,5"]) expect(microsOf(text)).toBeNull();
  });
});

it("counts with its noun", () => {
  expect(countLine(1, "run")).toBe("1 run");
  expect(countLine(2, "entry", "entries")).toBe("2 entries");
});
