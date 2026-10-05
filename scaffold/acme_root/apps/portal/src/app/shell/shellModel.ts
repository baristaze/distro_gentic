// Pure: the left bar's sessions. Each is grouped by what it asks of a
// person: Needs you (parked on a person), Running (running, pending, or
// parked on anything else), Recent (idle, the newest thirty). A sub-agent
// nests under its parent, and a tree sits in the group of its most urgent
// member, so a child that needs a person lifts its tree into Needs you and
// is never hidden under a quiet parent. A support conversation is the
// dock's, and shows only under the platform assistant's filter. No React,
// no fetch.
import type { AgentSessionView } from "@acme/client";
import { parkLine } from "../../features/session/sessionModel";
import type { SessionFilter } from "./sessionFilter";
import { listedFor } from "./supportModel";

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
  /** Its sub-agents, at every depth, and how many of them need a person:
   * what its row says once it folds them. */
  tree: { count: number; needsYou: number };
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
  if (!listedFor(session, filter.kind)) return false;
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
      tree: { count: 0, needsYou: 0 },
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
  // What each row holds beneath it.
  const count = (row: ShellRow): ShellRow["tree"] => {
    for (const child of row.children) {
      const below = count(child);
      row.tree.count += 1 + below.count;
      row.tree.needsYou += (child.dot === "needs" ? 1 : 0) + below.needsYou;
    }
    return row.tree;
  };
  roots.sort(newestFirst);
  const groups: ShellGroups = { needsYou: [], running: [], recent: [] };
  for (const root of roots) {
    sortChildren(root);
    count(root);
    const rank = urgency(root);
    if (rank === 0) groups.needsYou.push(root);
    else if (rank === 1) groups.running.push(root);
    else if (groups.recent.length < RECENT_MAX) groups.recent.push(root);
  }
  return groups;
}

/** A session that started to need its person, as its toast says it: its
 * title and what it needs ("Approve run_command", its question). */
export interface NeedsYouNotice {
  id: string;
  title: string;
  need: string;
  /** Whether it waits for an answer to the agent's question, which a read
   * of its history words. */
  asks: boolean;
}

/** What a session that needs its person needs, in a few words. `held`
 * names the tool of the call it holds for a decision, when that is known. */
export function needWords(session: Pick<AgentSessionView, "status" | "park" | "archived_at">, held?: string): string {
  const park = session.park;
  if (park?.unlock === "approval") return held ? `Approve ${held}` : "Decide on a held call";
  if (park?.unlock === "answer") return "Answer its question";
  return statusWords(session, held);
}

/** The sessions of the person's that need them now, by id: one they
 * started, or a sub-agent anywhere in a tree they started. */
export function needingYou(
  sessions: readonly AgentSessionView[],
  me: string | null,
  held?: ReadonlyMap<string, string>,
): Map<string, NeedsYouNotice> {
  const byId = new Map(sessions.map((session) => [session.id, session]));
  const mine = (session: AgentSessionView) => session.created_by === me || byId.get(session.root_id)?.created_by === me;
  const needing = new Map<string, NeedsYouNotice>();
  if (me === null) return needing;
  for (const session of byId.values()) {
    if (!needsYou(session) || !mine(session)) continue;
    needing.set(session.id, { id: session.id, title: session.title.trim() || "Untitled", need: needWords(session, held?.get(session.id)), asks: session.park?.unlock === "answer" });
  }
  return needing;
}

/** The toasts on show, and the sessions that needed the person when the
 * list was last read: null before the first read. */
export interface ToastState {
  seen: ReadonlySet<string> | null;
  toasts: readonly NeedsYouNotice[];
}

export const NO_TOASTS: ToastState = { seen: null, toasts: [] };
/** The most toasts on show: the newest. */
export const TOASTS_SHOWN = 3;

const sameNotice = (a: NeedsYouNotice, b: NeedsYouNotice | undefined) => b !== undefined && a.id === b.id && a.title === b.title && a.need === b.need;

/** The toasts once the list is read again: a session that starts to need
 * the person raises one, unless its page is the one open; one that no
 * longer needs them, or whose page opened, drops its own. What needed them
 * at the first read is in the left bar already and raises none. The same
 * state comes back when nothing changed. */
export function nextToasts(state: ToastState, needing: ReadonlyMap<string, NeedsYouNotice>, open: string | null): ToastState {
  const ids = new Set(needing.keys());
  if (state.seen === null) return { seen: ids, toasts: [] };
  const fresh = [...needing.values()].filter((notice) => !state.seen!.has(notice.id) && notice.id !== open);
  const kept = state.toasts.flatMap((toast) => (toast.id !== open && needing.has(toast.id) ? [needing.get(toast.id)!] : []));
  const toasts = [...kept, ...fresh].slice(-TOASTS_SHOWN);
  const unchanged =
    toasts.length === state.toasts.length &&
    toasts.every((toast, index) => sameNotice(toast, state.toasts[index])) &&
    ids.size === state.seen.size &&
    [...ids].every((id) => state.seen!.has(id));
  return unchanged ? state : { seen: ids, toasts };
}

/** For each child, the first session beneath it, at any depth, that waits on
 * a person: a sub-agent's own sub-agent that needs them shows on each
 * session above it. Read from the sessions the shell keeps (every parked
 * one, and the newest), linked by `parent_id`, with no read of its own. A
 * child with none waiting beneath it is not in the map. */
export function waitingBeneath(
  sessions: readonly AgentSessionView[],
  children: readonly Pick<AgentSessionView, "id">[],
): Map<string, { id: string; title: string }> {
  const below = new Map<string, AgentSessionView[]>();
  const listed = new Set<string>();
  for (const session of sessions) {
    if (listed.has(session.id) || session.parent_id === null) continue;
    listed.add(session.id);
    below.set(session.parent_id, [...(below.get(session.parent_id) ?? []), session]);
  }
  const found = new Map<string, { id: string; title: string }>();
  for (const child of children) {
    const seen = new Set([child.id]);
    const next = [...(below.get(child.id) ?? [])];
    for (let session = next.shift(); session !== undefined; session = next.shift()) {
      if (seen.has(session.id)) continue;
      seen.add(session.id);
      if (needsYou(session)) {
        found.set(child.id, { id: session.id, title: session.title.trim() || "Untitled" });
        break;
      }
      next.push(...(below.get(session.id) ?? []));
    }
  }
  return found;
}

/** What a row that folds its sub-agents says of them: "2 sub-agents · 1
 * needs you". */
export function treeWords(tree: ShellRow["tree"]): string {
  const many = tree.count === 1 ? "1 sub-agent" : `${tree.count} sub-agents`;
  if (tree.needsYou === 0) return many;
  return `${many} · ${tree.needsYou} ${tree.needsYou === 1 ? "needs" : "need"} you`;
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
