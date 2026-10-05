// Pure: a session's right pane. Its tabs open on demand and close, a "+"
// lists the views not open, and a tab may open itself once, when it first
// has something. Each session keeps its own pane: its width, its open tabs,
// the active one, and whether a person hid it. No React, no storage.
import { clampWidth, type PaneBounds } from "../../design/kit/splitterModel";
import { childPhase, editOf, lineCount, type Call, type ChildState } from "./timelineModel";

/** The pane: 440 pixels at first, between 320 and 760. */
export const PANE: PaneBounds = { min: 320, max: 760, initial: 440 };

/** How many sessions keep their pane; the one changed longest ago goes first. */
export const KEPT_PANES = 100;

export interface PaneState {
  width: number;
  /** The open tabs, in the order they opened. */
  tabs: readonly string[];
  /** The tab drawn while the pane shows; null when no tab is open. */
  active: string | null;
  /** Hidden by a person: its tabs stay, and nothing shows it but a person. */
  hidden: boolean;
  /** The tabs that have opened themselves: each does so once a session. */
  selfOpened: readonly string[];
  /** The call a click opened last: the one Step shows; null shows the last call. */
  step: string | null;
}

export const NEW_PANE: PaneState = { width: PANE.initial, tabs: [], active: null, hidden: false, selfOpened: [], step: null };

/** The tab drawn now, or null when the pane does not show. */
export function shownTab(pane: PaneState): string | null {
  return pane.hidden ? null : pane.active;
}

/** Opens a tab, or goes to it when it is open, and shows the pane. */
export function openTab(pane: PaneState, id: string): PaneState {
  const tabs = pane.tabs.includes(id) ? pane.tabs : [...pane.tabs, id];
  return { ...pane, tabs, active: id, hidden: false };
}

/** Opens a call in a tab, Step or the one its tool names. */
export function openCall(pane: PaneState, tab: string, callId: string): PaneState {
  return { ...openTab(pane, tab), step: callId };
}

/** Closes a tab. When it was the active one, the tab after it takes its
 * place, else the one before; the pane shows nothing once the last closes. */
export function closeTab(pane: PaneState, id: string): PaneState {
  const at = pane.tabs.indexOf(id);
  if (at < 0) return pane;
  const tabs = pane.tabs.filter((tab) => tab !== id);
  const active = pane.active === id ? (tabs[at] ?? tabs[at - 1] ?? null) : pane.active;
  return { ...pane, tabs, active };
}

/** Hides the pane while it shows, and shows it otherwise: at its active tab,
 * or at `fallback` when no tab is open. */
export function togglePane(pane: PaneState, fallback: string): PaneState {
  if (shownTab(pane) !== null) return { ...pane, hidden: true };
  if (pane.active === null) return openTab(pane, fallback);
  return { ...pane, hidden: false };
}

export function resizePane(pane: PaneState, width: number): PaneState {
  return { ...pane, width: clampWidth(width, PANE) };
}

/** The tabs that would open themselves now, in their order. Each that has
 * not done so before opens and becomes the active one, and is recorded, so
 * it never opens itself again in this session: a person who closes it keeps
 * it closed. A pane a person hid stays hidden; the tab waits in it. */
export function openThemselves(pane: PaneState, wanting: readonly string[]): PaneState {
  const fresh = wanting.filter((id) => !pane.selfOpened.includes(id));
  if (fresh.length === 0) return pane;
  let next: PaneState = { ...pane, selfOpened: [...pane.selfOpened, ...fresh] };
  for (const id of fresh) next = { ...next, tabs: next.tabs.includes(id) ? next.tabs : [...next.tabs, id], active: id };
  return next;
}

/** A tab as the pane weighs it: whether this session has anything for it,
 * and whether it opens itself now. */
export interface TabOffer {
  id: string;
  offered: boolean;
  opensItself: boolean;
}

/** What "+" lists: each tab the session offers that is not open, in order. */
export function addable(pane: PaneState, offers: readonly TabOffer[]): string[] {
  return offers.filter((offer) => offer.offered && !pane.tabs.includes(offer.id)).map((offer) => offer.id);
}

/** The pane's open tabs that are still tabs of the portal, its active one
 * moved when it is gone: a tab a product dropped never draws. */
export function knownTabs(pane: PaneState, known: ReadonlySet<string>): PaneState {
  if (pane.tabs.every((tab) => known.has(tab))) return pane;
  const tabs = pane.tabs.filter((tab) => known.has(tab));
  const active = pane.active !== null && known.has(pane.active) ? pane.active : (tabs[tabs.length - 1] ?? null);
  return { ...pane, tabs, active };
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? [...new Set(value.filter((item): item is string => typeof item === "string" && item !== ""))] : [];

/** One pane as stored: a value it does not name, or names wrongly, is the
 * new pane's; an active tab that is not open is none. */
export function parsePane(stored: unknown): PaneState {
  if (typeof stored !== "object" || stored === null) return NEW_PANE;
  const kept = stored as Partial<Record<keyof PaneState, unknown>>;
  const tabs = strings(kept.tabs);
  const active = typeof kept.active === "string" && tabs.includes(kept.active) ? kept.active : (tabs[tabs.length - 1] ?? null);
  return {
    width: clampWidth(typeof kept.width === "number" ? kept.width : PANE.initial, PANE),
    tabs,
    active,
    hidden: kept.hidden === true,
    selfOpened: strings(kept.selfOpened),
    step: typeof kept.step === "string" && kept.step !== "" ? kept.step : null,
  };
}

/** Every session's pane as stored, each parsed, at most the kept number. */
export function parsePanes(stored: unknown): Record<string, PaneState> {
  if (typeof stored !== "object" || stored === null || Array.isArray(stored)) return {};
  const entries = Object.entries(stored as Record<string, unknown>).slice(-KEPT_PANES);
  return Object.fromEntries(entries.map(([id, pane]) => [id, parsePane(pane)]));
}

/** The panes with one session's changed: it moves to the end, and the panes
 * changed longest ago go once more than the kept number would stay. */
export function rememberPane(panes: Readonly<Record<string, PaneState>>, id: string, pane: PaneState): Record<string, PaneState> {
  const rest = Object.entries(panes).filter(([key]) => key !== id);
  return Object.fromEntries([...rest, [id, pane] as const].slice(-KEPT_PANES));
}

/** One file a session changed: the lines its edits added and removed, and
 * the last call that changed it, which a click opens. `cut` when the view
 * cut one of its edits, whose lines it cannot count. */
export interface ChangedFile {
  path: string;
  added: number;
  removed: number;
  edits: number;
  lastCall: string;
  cut: boolean;
}

/** Each file the session's answered edits and writes changed, in the order
 * it first changed them. */
export function changedFiles(calls: readonly Call[]): ChangedFile[] {
  const files = new Map<string, ChangedFile>();
  for (const call of calls) {
    const edit = call.state === "done" ? editOf(call) : null;
    if (!edit) continue;
    const before = files.get(edit.path) ?? { path: edit.path, added: 0, removed: 0, edits: 0, lastCall: call.id, cut: false };
    files.set(edit.path, {
      ...before,
      added: before.added + lineCount(edit.added),
      removed: before.removed + lineCount(edit.removed),
      edits: before.edits + 1,
      lastCall: call.id,
      cut: before.cut || edit.cut,
    });
  }
  return [...files.values()];
}

/** The plan the session wrote last, or null before it wrote one. */
export function latestPlan(calls: readonly Call[]): { text: string; at: string; callId: string } | null {
  for (let at = calls.length - 1; at >= 0; at -= 1) {
    const call = calls[at]!;
    const plan = call.tool === "write_plan" ? call.input?.plan : undefined;
    if (typeof plan === "string" && plan.trim()) return { text: plan, at: call.startedAt, callId: call.id };
  }
  return null;
}

/** The tools whose answered call means the session delivered: it opened a
 * pull request, or its result was taken. */
export const DELIVERING_TOOLS: ReadonlySet<string> = new Set(["open_pull_request", "submit_result"]);

export function delivered(calls: readonly Call[]): boolean {
  return calls.some((call) => DELIVERING_TOOLS.has(call.tool) && call.state === "done");
}

/** The call the Step tab shows: the one named, else the last. */
export function stepOf(calls: readonly Call[], id: string | null): Call | null {
  return (id !== null ? calls.find((call) => call.id === id) : undefined) ?? calls[calls.length - 1] ?? null;
}

/** A group of the Sub-agents tab: the children that need a person, those
 * that work or wait on something that clears by itself, and those done. */
export interface ChildGroup {
  phase: "needs_you" | "working" | "done";
  label: string;
  children: ChildState[];
}

const CHILD_GROUPS: readonly Omit<ChildGroup, "children">[] = [
  { phase: "needs_you", label: "Needs you" },
  { phase: "working", label: "Working" },
  { phase: "done", label: "Done" },
];

/** A session's children grouped by where they stand, in their order, each
 * group that holds one. */
export function childGroups(children: readonly ChildState[]): ChildGroup[] {
  const groupOf = (child: ChildState): ChildGroup["phase"] => {
    const phase = childPhase(child);
    return phase === "waiting" ? "working" : phase;
  };
  return CHILD_GROUPS.map((group) => ({ ...group, children: children.filter((child) => groupOf(child) === group.phase) })).filter((group) => group.children.length > 0);
}
