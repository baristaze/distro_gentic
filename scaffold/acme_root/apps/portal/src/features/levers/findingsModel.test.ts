import { expect, it } from "vitest";
import type { levers } from "@acme/client";
import { CHECK_LABEL, findingLines } from "./findingsModel";

it("names every check in words", () => {
  expect(Object.keys(CHECK_LABEL).sort()).toEqual(["contradiction", "past_session_bound", "repeated_phrase", "unbounded_retry", "unknown_name"]);
});

it("keeps each finding's detail and excerpt, in order", () => {
  const found: levers.FindingView[] = [
    { check: "unbounded_retry", detail: "“keep retrying” with no stopping condition", excerpt: "Keep retrying until it is green." },
    { check: "past_session_bound", detail: "9000 characters, past the 8000 a session holds whole", excerpt: null },
  ];
  expect(findingLines(found)).toEqual([
    { label: "A retry with no stopping condition", detail: "“keep retrying” with no stopping condition", excerpt: "Keep retrying until it is green." },
    { label: "Longer than a session holds whole", detail: "9000 characters, past the 8000 a session holds whole", excerpt: null },
  ]);
});
