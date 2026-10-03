import { expect, it } from "vitest";
import type { BudgetUsageView } from "@acme/client";
import { usageRow, windowLine } from "./usageModel";

const nameOf = { person: (id: string) => (id === "u1" ? "Ada" : "a former member"), project: (id: string) => (id === "p1" ? "Docs" : "a removed project") };
const usage = (budget: Partial<BudgetUsageView["budget"]>, spent: number, held = 0): BudgetUsageView => ({
  budget: { id: "b1", scope_kind: "tenant", scope_key: "o1", window_kind: "month", window_seconds: null, cost_micros: 10_000_000, tokens: null, version: 1, ...budget },
  window_start: "2026-10-01T00:00:00Z",
  spent_cost_micros: spent,
  held_cost_micros: held,
  spent_tokens: 1200,
  held_tokens: 0,
});

it("shows a budget's spend and holds against its amount", () => {
  expect(usageRow(usage({}, 2_500_000, 500_000), nameOf)).toEqual({
    id: "b1",
    scope: "the org",
    window: "this month",
    cost: "2.50 spent, 0.50 held, of 10.00",
    tokens: `${(1200).toLocaleString()} spent, no cap`,
    used: 30,
  });
});

it("names a person or a project it bounds", () => {
  expect(usageRow(usage({ scope_kind: "person", scope_key: "u1" }, 0), nameOf).scope).toBe("Ada");
  expect(usageRow(usage({ scope_kind: "project", scope_key: "p1" }, 0), nameOf).scope).toBe("the project Docs");
});

it("says a window in words", () => {
  expect(windowLine("day", null)).toBe("today");
  expect(windowLine("span", 7_200)).toBe("the last 2 hours");
});

it("has no share when it bounds neither cost nor tokens", () => {
  expect(usageRow(usage({ cost_micros: null }, 0), nameOf).used).toBeNull();
});
