// Pure: the left bar's sessions. Each is grouped by what it asks of a
// person: Needs you (parked on a person), Running (running, pending, or
// parked on anything else), Recent (idle, the newest thirty). A sub-agent
// nests under its parent, and a tree sits in the group of its most urgent
// member, so a child that needs a person lifts its tree into Needs you and
// is never hidden under a quiet parent. No React, no fetch.
import type { AgentSessionView } from "@acme/client";
import { parkLine } from "../../features/session/sessionModel";
import type { SessionFilter } from "./sessionFilter";

export { DEFAULT_FILTER, filtering, parseFilter, type SessionFilter } from "./sessionFilter";

export type Group = "needs_you" | "running" | "recent";

/** How a row's dot looks: orange when it needs you, pulsing while it runs. */
export type Dot = "needs" | "running" | "waiting" | "done" | "archived";

export interface ShellRow {
  id: string;
  title: string;
  kind: string;
  /** The status in words: "Needs your decision: run_command", "Done". */
  words: string;
  dot: Dot;
  /** When it started, as the server gave it. */
  at: string;
  children: ShellRow[];
}

export interface ShellGroups {
  needsYou: ShellRow[];
  running: ShellRow[];
  recent: ShellRow[];
}

export const RECENT_MAX = 30;

/** A session waits on a person: it is parked for one. */
export function needsYou(session: Pick<AgentSessionView, "status" | "park" | "archived_at">): boolean {
  return session.archived_at === null && session.status === "parked" && session.park?.reason === "person";
}

export function groupOf(session: Pick<AgentSessionView, "status" | "park" | "archived_at">): Group {
  if (needsYou(session)) return "needs_you";
  if (session.archived_at === null && session.status !== "idle") return "running";
  return "recent";
}

const WAITS: Record<string, string> = {
  provider: "Waiting on the model provider",
  budget: "Waiting on its budget",
  job: "Waiting on work it started",
  children: "Waiting on its sub-agents",
  handover: "A person has control",
  pause: "Paused",
};

/** The status in words. `held` names the tool of the call it holds for a
 * decision, when that is known. */
export function statusWords(session: Pick<AgentSessionView, "status" | "park" | "archived_at">, held?: string): string {
  if (session.archived_at !== null) return "Archived";
  const park = session.park;
  switch (session.status) {
    case "running":
      return "Running";
    case "pending":
      return "Starting";
    case "idle":
      return "Done";
    case "parked":
      if (park === null) return "Waiting";
      if (park.reason === "person") {
        if (park.unlock === "approval") return held ? `Needs your decision: ${held}` : "Needs your decision";
        return `Needs you: ${parkLine(park).unlock}`;
      }
      if (park.reason === "resource") return park.unlock === "workspace" ? "Waiting for a workspace" : "Waiting for a resource";
      return WAITS[park.reason] ?? "Waiting";
  }
}

function dotOf(session: AgentSessionView): Dot {
  if (session.archived_at !== null) return "archived";
  if (needsYou(session)) return "needs";
  if (session.status === "running") return "running";
  if (session.status === "idle") return "done";
  return "waiting";
}

const RANK: Record<Group, number> = { needs_you: 0, running: 1, recent: 2 };

function kept(session: AgentSessionView, filter: SessionFilter, me: string | null): boolean {
  if (session.archived_at !== null && !filter.archived) return false;
  if (filter.owner === "mine" && session.created_by !== me) return false;
  if (filter.kind && session.kind !== filter.kind) return false;
  if (filter.status !== "any" && session.status !== filter.status) return false;
  return true;
}

const newestFirst = (a: { at: string }, b: { at: string }) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0);
const oldestFirst = (a: { at: string }, b: { at: string }) => -newestFirst(a, b);

/** The sessions the left bar shows, grouped and nested. A session read
 * twice counts once; a sub-agent whose parent is not shown stands as a row
 * of its own. `held` maps a session to the tool it holds for a decision. */
export function shellGroups(
  sessions: readonly AgentSessionView[],
  options: { filter: SessionFilter; me: string | null; held?: ReadonlyMap<string, string> },
): ShellGroups {
  const byId = new Map<string, AgentSessionView>();
  for (const session of sessions) {
    if (!byId.has(session.id) && kept(session, options.filter, options.me)) byId.set(session.id, session);
  }
  const rows = new Map<string, ShellRow>();
  for (const session of byId.values()) {
    rows.set(session.id, {
      id: session.id,
      title: session.title.trim() || "Untitled",
      kind: session.kind,
      words: statusWords(session, options.held?.get(session.id)),
      dot: dotOf(session),
      at: session.created_at,
      children: [],
    });
  }
  const roots: ShellRow[] = [];
  for (const session of byId.values()) {
    const row = rows.get(session.id)!;
    const parent = session.parent_id === null ? undefined : rows.get(session.parent_id);
    if (parent) parent.children.push(row);
    else roots.push(row);
  }
  // A tree's group is its most urgent member's.
  const urgency = (row: ShellRow): number =>
    Math.min(RANK[groupOf(byId.get(row.id)!)], ...row.children.map(urgency));
  const sortChildren = (row: ShellRow): void => {
    row.children.sort(oldestFirst);
    row.children.forEach(sortChildren);
  };
  roots.sort(newestFirst);
  const groups: ShellGroups = { needsYou: [], running: [], recent: [] };
  for (const root of roots) {
    sortChildren(root);
    const rank = urgency(root);
    if (rank === 0) groups.needsYou.push(root);
    else if (rank === 1) groups.running.push(root);
    else if (groups.recent.length < RECENT_MAX) groups.recent.push(root);
  }
  return groups;
}

/** A time as the row shows it: "now", "5m", "3h", "2d", or the day. */
export function ago(iso: string, now: Date): string {
  const at = new Date(iso);
  const seconds = (now.getTime() - at.getTime()) / 1000;
  if (Number.isNaN(seconds)) return "";
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 7 * 86_400) return `${Math.floor(seconds / 86_400)}d`;
  return at.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
