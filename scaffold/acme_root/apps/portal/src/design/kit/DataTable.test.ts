// @vitest-environment jsdom
// A table's rows in the order its header asks for: a missing value last,
// numbers as numbers, words as a person reads them.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { DataTable, type Column } from "./DataTable";
import { nextSort, sortRows } from "./tableModel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

interface Row {
  name: string;
  size: number | null;
}

const ROWS: Row[] = [
  { name: "run 10", size: 3 },
  { name: "run 2", size: null },
  { name: "run 1", size: 20 },
];

describe("sortRows", () => {
  it("sorts words as a person reads them, and numbers as numbers", () => {
    expect(sortRows(ROWS, (row) => row.name, "ascending").map((row) => row.name)).toEqual(["run 1", "run 2", "run 10"]);
    expect(sortRows(ROWS, (row) => row.size, "descending").map((row) => row.size)).toEqual([20, 3, null]);
  });

  it("puts a missing value last whichever way the column runs", () => {
    expect(sortRows(ROWS, (row) => row.size, "ascending").map((row) => row.size)).toEqual([3, 20, null]);
  });

  it("turns the same column around, and starts another ascending", () => {
    expect(nextSort({ column: "a", direction: "ascending" }, "a")).toEqual({ column: "a", direction: "descending" });
    expect(nextSort({ column: "a", direction: "descending" }, "b")).toEqual({ column: "b", direction: "ascending" });
  });
});

describe("DataTable", () => {
  const columns: Column<Row>[] = [
    { key: "name", header: "Name", cell: (row) => row.name, sortValue: (row) => row.name },
    { key: "size", header: "Size", cell: (row) => String(row.size ?? "") },
  ];

  it("sorts on a click of a header and says how it is sorted", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => root.render(createElement(DataTable<Row>, { columns, rows: ROWS, rowKey: (row) => row.name, empty: "None" })));
    const names = () => [...container.querySelectorAll("tbody tr")].map((row) => row.firstChild!.textContent);
    expect(names()).toEqual(["run 10", "run 2", "run 1"]);
    await act(async () => container.querySelector<HTMLButtonElement>("th button")!.click());
    expect(names()).toEqual(["run 1", "run 2", "run 10"]);
    expect(container.querySelector("th")!.getAttribute("aria-sort")).toBe("ascending");
    expect(container.querySelectorAll("th button")).toHaveLength(1);
    await act(async () => root.render(createElement(DataTable<Row>, { columns, rows: [], rowKey: (row) => row.name, empty: "No sessions yet" })));
    expect(container.querySelector("tbody")!.textContent).toBe("No sessions yet");
    await act(async () => root.unmount());
  });
});
