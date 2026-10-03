// @vitest-environment jsdom
// A command's output: colour codes dropped, a rewritten line shows its last
// state, a line split across chunks is joined, and a long output keeps its tail.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { LogView } from "./LogView";
import { logLines, stripAnsi } from "./logModel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const ESC = String.fromCharCode(27);

describe("logLines", () => {
  it("drops a terminal's colour codes", () => {
    expect(stripAnsi(`${ESC}[31mred${ESC}[0m and ${ESC}]0;title${String.fromCharCode(7)}plain`)).toBe("red and plain");
  });

  it("joins a line split across chunks of one stream, and keeps the streams apart", () => {
    const { lines } = logLines([
      { stream: "stdout", text: "comp" },
      { stream: "stdout", text: "iling\nok\n" },
      { stream: "stderr", text: "warning: slow\n" },
    ]);
    expect(lines).toEqual([
      { no: 1, stream: "stdout", text: "compiling" },
      { no: 2, stream: "stdout", text: "ok" },
      { no: 3, stream: "stderr", text: "warning: slow" },
    ]);
  });

  it("shows what a carriage return left on the line, and drops a CRLF's return", () => {
    expect(logLines("10%\r50%\r100%\ndone\r\n").lines.map((line) => line.text)).toEqual(["100%", "done"]);
  });

  it("keeps the tail of a long output and counts what it dropped", () => {
    const text = Array.from({ length: 5 }, (_, index) => `line ${index + 1}`).join("\n");
    const kept = logLines(text, 2);
    expect([kept.hidden, kept.lines.map((line) => line.no)]).toEqual([3, [4, 5]]);
  });
});

describe("LogView", () => {
  it("is a log a screen reader names, its error lines marked, its dropped lines counted", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () =>
      root.render(createElement(LogView, { label: "Output", limit: 1, output: [{ stream: "stdout", text: "a\n" }, { stream: "stderr", text: "b\n" }] })),
    );
    const log = container.querySelector("[role='log']")!;
    expect(log.getAttribute("aria-label")).toBe("Output");
    expect(log.textContent).toContain("1 earlier line not shown");
    expect(log.querySelector("[data-stream='stderr']")!.textContent).toBe("2b");
    await act(async () => root.unmount());
  });
});
