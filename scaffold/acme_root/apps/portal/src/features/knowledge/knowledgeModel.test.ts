import { describe, expect, it } from "vitest";
import { EMPTY_DRAFT, entryRequest, statusFilter } from "./knowledgeModel";

describe("entryRequest", () => {
  const draft = { ...EMPTY_DRAFT, title: " Release day ", trigger: "release, deploy , release,", text: " Releases go out on **Tuesday**. " };
  it("is a title, its words, and its text", () => {
    expect(entryRequest(draft)).toEqual({ request: { title: "Release day", trigger: ["release", "deploy"], text: "Releases go out on **Tuesday**." } });
  });
  it("refuses what the API refuses, saying why", () => {
    expect(entryRequest({ ...draft, title: "" })).toEqual({ problem: "Give the entry a title." });
    expect(entryRequest({ ...draft, trigger: " , " })).toEqual({ problem: "Name at least one word that recalls it." });
    expect(entryRequest({ ...draft, trigger: Array.from({ length: 21 }, (_, i) => `w${i}`).join(",") })).toEqual({
      problem: "An entry is recalled by at most 20 words.",
    });
    expect(entryRequest({ ...draft, text: "x".repeat(10_001) })).toEqual({ problem: "An entry is at most 10000 characters." });
  });
});

it("reads the state from the address bar, kept by default", () => {
  expect(statusFilter("suggested")).toBe("suggested");
  expect(statusFilter("anything")).toBe("reviewed");
  expect(statusFilter(null)).toBe("reviewed");
});
