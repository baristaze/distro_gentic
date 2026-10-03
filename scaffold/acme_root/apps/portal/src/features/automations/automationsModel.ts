// Pure: the tenant's automations as the screens show them, and the request a
// person's form makes, refused with a reason wherever the API would refuse
// it. A trigger is an event that passes its filters or a schedule; an action
// starts a session or messages a standing one; the limits bound what its
// runs spend and how often they start. No React, no fetch.
import type { AutomationRequest, AutomationView, ProjectView, Role } from "@acme/client";
import { costLine, microsOf } from "../../app/recordModel";

export const NAME_MAX = 200;
export const BRIEF_MAX = 20_000;
export const KIND_MAX = 200;
export const TITLE_MAX = 200;
export const FILTER_MAX = 50;
/** What a new automation takes that the form does not ask: the API's own
 * defaults, a queue of 50 and a chain of 3. */
export const QUEUE_DEPTH = 50;
export const HOP_LIMIT = 3;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** An ISO 8601 duration (`PT1H`, `P1D`, `PT1M30S`) in seconds; null for any
 * other text. */
export function secondsOf(duration: string): number | null {
  const match = /^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$/.exec(duration);
  if (!match || duration === "P" || duration.endsWith("T")) return null;
  const [, weeks = "0", days = "0", hours = "0", minutes = "0", seconds = "0"] = match;
  return Number(weeks) * 604_800 + Number(days) * 86_400 + Number(hours) * 3_600 + Number(minutes) * 60 + Number(seconds);
}

const UNITS: readonly [number, string][] = [
  [86_400, "day"],
  [3_600, "hour"],
  [60, "minute"],
  [1, "second"],
];

/** A span in words: "1 day", "2 hours 30 minutes". */
export function spanLine(seconds: number): string {
  const parts: string[] = [];
  let rest = Math.round(seconds);
  for (const [size, unit] of UNITS) {
    const count = Math.floor(rest / size);
    if (count > 0) parts.push(`${count} ${unit}${count === 1 ? "" : "s"}`);
    rest -= count * size;
  }
  return parts.join(" ") || "0 seconds";
}

/** How often, in words: "every day", "every 2 hours". */
export function everyLine(duration: string | null): string {
  const seconds = duration === null ? null : secondsOf(duration);
  if (seconds === null) return `every ${duration ?? ""}`.trim();
  const span = spanLine(seconds);
  return `every ${span.replace(/^1 /, "")}`;
}

/** Per a period, in words: "a day", "an hour", or "every 2 days". */
export function perLine(duration: string): string {
  const seconds = secondsOf(duration);
  if (seconds === 3_600) return "an hour";
  if (seconds === 86_400) return "a day";
  if (seconds === 604_800) return "a week";
  return everyLine(duration);
}

export function triggerLine(trigger: AutomationView["trigger"]): string {
  if (trigger.kind === "schedule") return everyLine(trigger.every);
  const filters = [
    trigger.integrations.length ? `from ${trigger.integrations.join(", ")}` : "",
    trigger.arrivals.length ? `arriving as ${trigger.arrivals.join(", ")}` : "",
    trigger.effects.length ? `routed to ${trigger.effects.join(", ")}` : "",
  ].filter(Boolean);
  return filters.length ? `on an event ${filters.join(", ")}` : "on any event";
}

export function actionLine(action: AutomationView["action"], projects: readonly Pick<ProjectView, "id" | "name">[]): string {
  if (action.kind === "message_session") return `message the session ${action.session_id ?? ""}`.trim();
  const project = action.project_id ? (projects.find((each) => each.id === action.project_id)?.name ?? "a project") : null;
  return `start a session of the kind ${action.agent_kind ?? ""}${project ? ` in ${project}` : ""}`;
}

export function limitsLine(limits: AutomationView["limits"]): string {
  const period = perLine(limits.period);
  return `${costLine(limits.cost_cap_micros)} ${period} (${costLine(limits.run_cap_micros)} a run), ${limits.rate} firings ${period}, ${limits.concurrency} at once${limits.queue ? `, a queue of ${limits.queue_depth}` : ""}`;
}

export interface AutomationRow {
  id: string;
  name: string;
  trigger: string;
  action: string;
  runsAs: string;
  enabled: boolean;
}

export const RUNS_AS_LABEL: Record<AutomationView["runs_as"], string> = { creator: "its maker", automation_principal: "the automation principal" };

export function automationRow(automation: AutomationView, projects: readonly Pick<ProjectView, "id" | "name">[]): AutomationRow {
  return {
    id: automation.id,
    name: automation.name,
    trigger: triggerLine(automation.trigger),
    action: actionLine(automation.action, projects),
    runsAs: RUNS_AS_LABEL[automation.runs_as],
    enabled: automation.enabled,
  };
}

export type SpanUnit = "minutes" | "hours" | "days";
const UNIT_SECONDS: Record<SpanUnit, number> = { minutes: 60, hours: 3_600, days: 86_400 };
/** The unit of a saved schedule no unit holds whole: it goes back as saved. */
export const AS_SAVED = "as_saved";

export const PERIODS = [
  { value: "PT1H", label: "an hour" },
  { value: "P1D", label: "a day" },
  { value: "P7D", label: "a week" },
] as const;

/** A saved span the form's choices do not hold, in words, as saved: "30
 * days, as saved". */
export function asSavedLine(duration: string): string {
  const seconds = secondsOf(duration);
  return `${seconds === null ? duration : spanLine(seconds)}, as saved`;
}

/** The periods the form offers: the three it knows, and the saved one when
 * it is none of them, so an edit never replaces it unasked. */
export function periodOptions(savedPeriod: string | null): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = PERIODS.map((each) => ({ ...each }));
  return savedPeriod === null ? options : [...options, { value: savedPeriod, label: asSavedLine(savedPeriod) }];
}

export interface AutomationDraft {
  name: string;
  triggerKind: "schedule" | "event";
  every: string;
  everyUnit: SpanUnit | typeof AS_SAVED;
  /** The saved schedule when no unit holds it whole; null otherwise. */
  savedEvery: string | null;
  integrations: string;
  arrivals: string;
  effects: string;
  actionKind: "start_session" | "message_session";
  agentKind: string;
  title: string;
  projectId: string;
  sessionId: string;
  brief: string;
  costCap: string;
  runCap: string;
  period: string;
  /** The saved period when it is none of `PERIODS`; null otherwise. */
  savedPeriod: string | null;
  rate: string;
  concurrency: string;
  queue: "no" | "yes";
  runsAs: AutomationView["runs_as"];
  enabled: "yes" | "no";
}

export const EMPTY_DRAFT: AutomationDraft = {
  name: "",
  triggerKind: "schedule",
  every: "1",
  everyUnit: "days",
  savedEvery: null,
  integrations: "",
  arrivals: "",
  effects: "",
  actionKind: "start_session",
  agentKind: "",
  title: "",
  projectId: "",
  sessionId: "",
  brief: "",
  costCap: "",
  runCap: "",
  period: "P1D",
  savedPeriod: null,
  rate: "10",
  concurrency: "1",
  queue: "no",
  runsAs: "creator",
  enabled: "yes",
};

/** The span a saved schedule fires at: the largest unit that holds it
 * whole; else the schedule as saved, which goes back unchanged. */
function everyOf(every: string): Pick<AutomationDraft, "every" | "everyUnit" | "savedEvery"> {
  const seconds = secondsOf(every);
  for (const unit of ["days", "hours", "minutes"] as const) {
    if (seconds !== null && seconds > 0 && seconds % UNIT_SECONDS[unit] === 0) return { every: String(seconds / UNIT_SECONDS[unit]), everyUnit: unit, savedEvery: null };
  }
  return { every: String(Math.max(1, Math.round((seconds ?? 60) / 60))), everyUnit: AS_SAVED, savedEvery: every };
}

/** A saved period as the form holds it: one of `PERIODS` when it is that
 * span, else the period as saved, which goes back unchanged. */
function periodOf(period: string): Pick<AutomationDraft, "period" | "savedPeriod"> {
  const seconds = secondsOf(period);
  const known = PERIODS.find((each) => secondsOf(each.value) === seconds);
  return known ? { period: known.value, savedPeriod: null } : { period, savedPeriod: period };
}

/** The form as the saved automation stands, to edit. */
export function draftOf(automation: AutomationView): AutomationDraft {
  const { trigger, action, limits } = automation;
  const every = trigger.every ? everyOf(trigger.every) : { every: EMPTY_DRAFT.every, everyUnit: EMPTY_DRAFT.everyUnit, savedEvery: null };
  return {
    name: automation.name,
    triggerKind: trigger.kind,
    ...every,
    integrations: trigger.integrations.join(", "),
    arrivals: trigger.arrivals.join(", "),
    effects: trigger.effects.join(", "),
    actionKind: action.kind,
    agentKind: action.agent_kind ?? "",
    title: action.title ?? "",
    projectId: action.project_id ?? "",
    sessionId: action.session_id ?? "",
    brief: action.brief,
    costCap: String(limits.cost_cap_micros / 1_000_000),
    runCap: String(limits.run_cap_micros / 1_000_000),
    ...periodOf(limits.period),
    rate: String(limits.rate),
    concurrency: String(limits.concurrency),
    queue: limits.queue ? "yes" : "no",
    runsAs: automation.runs_as,
    enabled: automation.enabled ? "yes" : "no",
  };
}

/** The words of a filter, split on commas, each trimmed, none empty. */
export function wordsOf(text: string): string[] {
  return text
    .split(",")
    .map((word) => word.trim())
    .filter(Boolean);
}

function wholeOf(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d{1,9}$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value > 0 ? value : null;
}

/** What a saved automation holds that the form does not show: its queue
 * depth, its hop limit, and whether its own events fire it. A new one
 * takes the API's defaults for them. */
export type KeptFields = Pick<AutomationView, "own_events"> & { limits: Pick<AutomationView["limits"], "queue_depth" | "hop_limit"> };

/** The request a draft makes, or the first reason it may not be saved. An
 * edit carries what the form does not show as it stood. Where a session
 * must start in a project, a start names one. */
export function automationRequest(
  draft: AutomationDraft,
  { kept = null, projectRequired = false }: { kept?: KeptFields | null; projectRequired?: boolean } = {},
): { request: AutomationRequest } | { problem: string } {
  const name = draft.name.trim();
  if (!name) return { problem: "Give the automation a name." };
  if (name.length > NAME_MAX) return { problem: `A name is at most ${NAME_MAX} characters.` };
  let trigger: AutomationRequest["trigger"];
  if (draft.triggerKind === "schedule" && draft.everyUnit === AS_SAVED && draft.savedEvery !== null) {
    trigger = { kind: "schedule", every: draft.savedEvery, integrations: [], arrivals: [], effects: [] };
  } else if (draft.triggerKind === "schedule") {
    const every = wholeOf(draft.every);
    if (every === null || draft.everyUnit === AS_SAVED) return { problem: "Say how often the schedule fires, as a whole number." };
    trigger = { kind: "schedule", every: `PT${every * UNIT_SECONDS[draft.everyUnit]}S`, integrations: [], arrivals: [], effects: [] };
  } else {
    const integrations = wordsOf(draft.integrations);
    const arrivals = wordsOf(draft.arrivals);
    const effects = wordsOf(draft.effects);
    if ([integrations, arrivals, effects].some((words) => words.length > FILTER_MAX)) return { problem: `A filter holds at most ${FILTER_MAX} words.` };
    trigger = { kind: "event", every: null, integrations, arrivals, effects };
  }
  const brief = draft.brief.trim();
  if (!brief) return { problem: "Write the brief the session is given." };
  if (brief.length > BRIEF_MAX) return { problem: `A brief is at most ${BRIEF_MAX} characters.` };
  let action: AutomationRequest["action"];
  if (draft.actionKind === "start_session") {
    const agentKind = draft.agentKind.trim();
    const title = draft.title.trim();
    if (!agentKind) return { problem: "Name the kind of session it starts." };
    if (agentKind.length > KIND_MAX) return { problem: `A kind is at most ${KIND_MAX} characters.` };
    if (!title) return { problem: "Give the sessions it starts a title." };
    if (title.length > TITLE_MAX) return { problem: `A title is at most ${TITLE_MAX} characters.` };
    if (projectRequired && !draft.projectId) return { problem: "Choose the project its sessions work in." };
    action = { kind: "start_session", brief, agent_kind: agentKind, title, project_id: draft.projectId || null, session_id: null };
  } else {
    const sessionId = draft.sessionId.trim();
    if (!UUID.test(sessionId)) return { problem: "Name the standing session by its id." };
    action = { kind: "message_session", brief, agent_kind: null, title: null, project_id: null, session_id: sessionId };
  }
  const costCap = microsOf(draft.costCap);
  if (costCap === null) return { problem: "Set the most its runs spend in a period, as an amount above zero." };
  const runCap = microsOf(draft.runCap);
  if (runCap === null) return { problem: "Set the most one run spends, as an amount above zero." };
  if (runCap > costCap) return { problem: "One run's cap is within the automation's." };
  const rate = wholeOf(draft.rate);
  if (rate === null) return { problem: "Set the most firings in a period, as a whole number above zero." };
  const concurrency = wholeOf(draft.concurrency);
  if (concurrency === null) return { problem: "Set the most runs at work at once, as a whole number above zero." };
  return {
    request: {
      name,
      trigger,
      action,
      limits: {
        cost_cap_micros: costCap,
        run_cap_micros: runCap,
        period: draft.period,
        rate,
        concurrency,
        queue: draft.queue === "yes",
        queue_depth: kept?.limits.queue_depth ?? QUEUE_DEPTH,
        hop_limit: kept?.limits.hop_limit ?? HOP_LIMIT,
      },
      runs_as: draft.runsAs,
      enabled: draft.enabled === "yes",
      own_events: kept?.own_events ?? false,
    },
  };
}

const RANK: Readonly<Record<string, number>> = { viewer: 0, member: 1, admin: 2, owner: 3 };

/** The roles a member may grant the automation principal: never above their
 * own, and never the owner's. */
export function principalRoles(mine: Role | undefined): Role[] {
  const rank = mine ? (RANK[mine] ?? -1) : -1;
  return (["admin", "member", "viewer"] as const).filter((role) => RANK[role]! <= rank);
}
