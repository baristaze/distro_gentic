// @vitest-environment jsdom
// A JSON value as a tree: a leaf shows its value, a container its size, and
// what is deeper than the open depth starts folded.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { JsonView } from "./JsonView";
import { foldedBelow, jsonRows, parseJsonText } from "./jsonModel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const VALUE = { name: "build", "a key": [1, true, null], nested: { deep: { deeper: "x" } } };

describe("jsonRows", () => {
  it("names each value by its path, with a leaf's value and a container's size", () => {
    const rows = jsonRows(VALUE, new Set());
    expect(rows.map((row) => [row.path, row.text])).toEqual([
      ["$", "3 keys"],
      ["$.name", '"build"'],
      ['$["a key"]', "3 items"],
      ['$["a key"][0]', "1"],
      ['$["a key"][1]', "true"],
      ['$["a key"][2]', "null"],
      ["$.nested", "1 key"],
      ["$.nested.deep", "1 key"],
      ["$.nested.deep.deeper", '"x"'],
    ]);
  });

  it("hides what a folded container holds, and folds below the open depth", () => {
    const folded = foldedBelow(VALUE, 2);
    expect([...folded]).toEqual(["$.nested.deep"]);
    expect(jsonRows(VALUE, folded).map((row) => row.path)).not.toContain("$.nested.deep.deeper");
  });

  it("reads only an object or an array as JSON worth a tree", () => {
    expect([parseJsonText(' {"a": 1} '), parseJsonText("42"), parseJsonText("{not json")]).toEqual([{ a: 1 }, undefined, undefined]);
  });
});

describe("JsonView", () => {
  it("unfolds a folded container on a click", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => root.render(createElement(JsonView, { value: VALUE, label: "Input" })));
    expect(container.textContent).not.toContain('"x"');
    const unfold = container.querySelector<HTMLButtonElement>("button[aria-label='Unfold $.nested.deep']")!;
    await act(async () => unfold.click());
    expect(container.textContent).toContain('"x"');
    await act(async () => root.unmount());
  });
});
