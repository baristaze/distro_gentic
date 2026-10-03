import { describe, expect, it } from "vitest";
import { gateLine, gatesOf, gatesText, publishRequest, EMPTY_DRAFT } from "./playbooksModel";

describe("gatesOf", () => {
  it("reads one gate a line, by tool or by class", () => {
    expect(gatesOf("approve tool git_push\n\n  deny class network ")).toEqual({
      gates: [
        { decision: "approve", tool: "git_push" },
        { decision: "deny", authorization_class: "network" },
      ],
    });
    expect(gatesText([{ decision: "approve", tool: "git_push" }, { decision: "deny", authorization_class: "network" }])).toBe(
      "approve tool git_push\ndeny class network",
    );
  });
  it("refuses a line that is not a gate, naming it", () => {
    expect(gatesOf("allow tool x")).toEqual({ problem: 'Line 1 of the gates is not a gate: write "approve tool <name>" or "deny class <name>".' });
    expect(gatesOf("approve tool\n")).toEqual({ problem: 'Line 1 of the gates is not a gate: write "approve tool <name>" or "deny class <name>".' });
    expect(gatesOf("\ndeny class Net-Work")).toEqual({ problem: "Line 2 of the gates names no class: a name is lowercase letters, digits, and underscores." });
  });
});

describe("publishRequest", () => {
  const draft = { ...EMPTY_DRAFT, name: " release-notes ", description: "Notes for a release.", body: "# Steps\n\n1. Read the log.", gates: "approve tool git_push" };
  it("is the name's next version with its gates", () => {
    expect(publishRequest(draft)).toEqual({
      request: { name: "release-notes", description: "Notes for a release.", body: "# Steps\n\n1. Read the log.", gates: [{ decision: "approve", tool: "git_push" }] },
    });
  });
  it("refuses a name the standard would not take", () => {
    expect(publishRequest({ ...draft, name: "Release Notes" })).toEqual({ problem: "A name is lowercase words joined by hyphens, such as release-notes." });
    expect(publishRequest({ ...draft, name: "" })).toEqual({ problem: "Give the playbook a name." });
    expect(publishRequest({ ...draft, description: " " })).toEqual({ problem: "Say what the playbook is for, and when to use it." });
    expect(publishRequest({ ...draft, body: "\n" })).toEqual({ problem: "Write the playbook's steps." });
  });
});

it("says what a gate does", () => {
  expect(gateLine({ decision: "approve", tool: "git_push" })).toBe("a call to git_push waits for a person's approval");
  expect(gateLine({ decision: "deny", authorization_class: "network" })).toBe("a call of class network is denied");
});
