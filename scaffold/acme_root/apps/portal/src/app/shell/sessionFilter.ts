// Pure: what the left bar's sessions list shows, kept as a preference: in
// which status, on which agent, and whether the archived ones too. The bar
// holds the person's own sessions, so whose they are is no part of it. It
// imports no code, so the preferences store reads it without the kit.
import type { AgentSessionStatus } from "@acme/client";

/** What the left bar shows of the person's own sessions: in which status,
 * on which agent, and whether the archived ones too. */
export interface SessionFilter {
  status: AgentSessionStatus | "any";
  /** An agent kind; empty for any. */
  kind: string;
  archived: boolean;
}

export const DEFAULT_FILTER: SessionFilter = { status: "any", kind: "", archived: false };

const STATUSES = new Set(["any", "running", "parked", "pending", "idle"]);

/** A stored filter, read field by field: a field it does not name, or names
 * wrongly, is the default's, and one it no longer holds is dropped. */
export function parseFilter(stored: unknown): SessionFilter {
  const kept = (typeof stored === "object" && stored !== null ? stored : {}) as Partial<Record<keyof SessionFilter, unknown>>;
  return {
    status: STATUSES.has(kept.status as string) ? (kept.status as SessionFilter["status"]) : DEFAULT_FILTER.status,
    kind: typeof kept.kind === "string" ? kept.kind : DEFAULT_FILTER.kind,
    archived: typeof kept.archived === "boolean" ? kept.archived : DEFAULT_FILTER.archived,
  };
}

/** Whether the filter narrows the list at all. */
export function filtering(filter: SessionFilter): boolean {
  return filter.status !== "any" || filter.kind !== "" || filter.archived;
}
