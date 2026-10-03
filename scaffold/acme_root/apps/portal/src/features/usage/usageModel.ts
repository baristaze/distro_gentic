// Pure: the org's usage, one row per budget: what it bounds, over which
// window, and what its current window spent and holds against its amount,
// in reference cost and in tokens. A limit counts settled spend and open
// holds together. No React, no fetch.
import type { BudgetUsageView } from "@acme/client";
import { costLine } from "../../app/recordModel";
import { spanLine } from "../automations/automationsModel";

export interface UsageRow {
  id: string;
  scope: string;
  window: string;
  cost: string;
  tokens: string;
  /** The share of the amount spent and held, 0 to 100 and past it; null
   * when the budget bounds neither. */
  used: number | null;
}

const WINDOWS: Record<string, string> = { life: "for good", hour: "this hour", day: "today", week: "this week", month: "this month" };

export function windowLine(kind: string, seconds: number | null): string {
  if (kind === "span" && seconds) return `the last ${spanLine(seconds)}`;
  return WINDOWS[kind] ?? kind;
}

/** What a budget bounds, in words, naming a person or a project where the
 * screen knows it. */
export function scopeLine(kind: string, key: string, nameOf: { person: (id: string) => string; project: (id: string) => string }): string {
  switch (kind) {
    case "tenant":
      return "the org";
    case "person":
      return nameOf.person(key);
    case "project":
      return `the project ${nameOf.project(key)}`;
    default:
      return `the ${kind} ${key}`;
  }
}

function amountLine(spent: number, held: number, amount: number | null, show: (value: number) => string): string {
  const total = amount === null ? "no cap" : `of ${show(amount)}`;
  return `${show(spent)} spent${held ? `, ${show(held)} held` : ""}, ${total}`;
}

const tokenCount = (value: number) => value.toLocaleString();

export function usageRow(usage: BudgetUsageView, nameOf: Parameters<typeof scopeLine>[2]): UsageRow {
  const { budget } = usage;
  const shares = [
    budget.cost_micros ? (usage.spent_cost_micros + usage.held_cost_micros) / budget.cost_micros : null,
    budget.tokens ? (usage.spent_tokens + usage.held_tokens) / budget.tokens : null,
  ].filter((share): share is number => share !== null);
  return {
    id: budget.id,
    scope: scopeLine(budget.scope_kind, budget.scope_key, nameOf),
    window: windowLine(budget.window_kind, budget.window_seconds),
    cost: amountLine(usage.spent_cost_micros, usage.held_cost_micros, budget.cost_micros, costLine),
    tokens: amountLine(usage.spent_tokens, usage.held_tokens, budget.tokens, tokenCount),
    used: shares.length ? Math.round(Math.max(...shares) * 100) : null,
  };
}
