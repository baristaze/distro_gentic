// The live view's streams: each read adds to what was held for a stream,
// a stream the read no longer names is gone, and a dropped buffer says so.
import { describe, expect, it, vi } from "vitest";
import type { LivePartView } from "@acme/client";
import { mergeLive } from "./live";

vi.mock("../app/api", () => ({ api: {} }));

function part(n: number, kind: LivePartView["kind"], text: string, tool: string | null = null, toolUseId: string | null = null): LivePartView {
  return { n, last: n, kind, text, tool, index: null, channel: null, tool_use_id: toolUseId };
}

describe("mergeLive", () => {
  it("joins a stream's parts of one kind and keeps the last place read", () => {
    const first = mergeLive([], [{ step_id: "a", first: 1, dropped: false, parts: [part(1, "text", "Hel"), part(2, "text", "lo")] }]);
    const second = mergeLive(first, [{ step_id: "a", first: 1, dropped: false, parts: [part(3, "tool_output", "ok", "run")] }]);
    expect(second).toEqual([
      {
        stepId: "a",
        last: 3,
        dropped: false,
        runs: [
          { kind: "text", tool: null, toolUseId: null, text: "Hello" },
          { kind: "tool_output", tool: "run", toolUseId: null, text: "ok" },
        ],
      },
    ]);
  });

  it("starts a new run where a tool's input names another call", () => {
    const read = mergeLive([], [
      { step_id: "a", first: 1, dropped: false, parts: [part(1, "tool_input", '{"a"', "run", "u1"), part(2, "tool_input", ":1}", "run", "u1"), part(3, "tool_input", "{}", "run", "u2")] },
    ]);
    expect(read[0]!.runs).toEqual([
      { kind: "tool_input", tool: "run", toolUseId: "u1", text: '{"a":1}' },
      { kind: "tool_input", tool: "run", toolUseId: "u2", text: "{}" },
    ]);
  });

  it("drops a stream the read no longer names, and keeps a stream with nothing new as it was", () => {
    const held = mergeLive([], [
      { step_id: "a", first: 1, dropped: false, parts: [part(1, "text", "x")] },
      { step_id: "b", first: 1, dropped: true, parts: [part(5, "text", "y")] },
    ]);
    const next = mergeLive(held, [{ step_id: "b", first: 1, dropped: false, parts: [] }]);
    expect(next).toEqual([{ stepId: "b", last: 5, dropped: true, runs: [{ kind: "text", tool: null, toolUseId: null, text: "y" }] }]);
  });
});
