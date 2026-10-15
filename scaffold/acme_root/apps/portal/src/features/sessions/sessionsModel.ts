// Pure: the sessions as Sessions shows them, in its two views (the person's
// own, and the org's to explore and join), the filters it offers and keeps
// in the address bar, and what a new session needs before it may start. No
// React, no fetch.
import type { agent_projects, agent_sessions, attribution } from "@acme/client";
import { listedFor } from "../../app/shell/supportModel";
import { standingOf, statusLine, type Standing, type Tone } from "../session/sessionModel";

/** A status, or the parked sessions that wait on a person: "Needs you". */
export type StatusFilter = agent_sessions.AgentSessionStatus | "any" | "needs_you";

export const STATUS_FILTERS: readonly { value: StatusFilter; label: string }[] = [
  { value: "any", label: "All" },
  { value: "needs_you", label: "Needs you" },
  { value: "running", label: "Running" },
  { value: "parked", label: "Parked" },
  { value: "pending", label: "Pending" },
  { value: "idle", label: "Idle" },
];

/** A filter from the address bar; anything else is every status. */
export function statusFilter(value: string | null): StatusFilter {
  return STATUS_FILTERS.some((filter) => filter.value === value) ? (value as StatusFilter) : "any";
}

/** The status the server is asked for: "Needs you" reads the parked ones. */
export function serverStatus(filter: StatusFilter): agent_sessions.AgentSessionStatus | null {
  if (filter === "any") return null;
  return filter === "needs_you" ? "parked" : filter;
}

/** Sessions' two views: the person's own, the ones they made or take part
 * in, first; and the org's, the org-wide ones any member may join. */
export type SessionsView = "mine" | "org";

export const VIEWS: readonly { value: SessionsView; label: string }[] = [
  { value: "mine", label: "Yours" },
  { value: "org", label: "The org's" },
];

/** The list the server is asked for: the person's own, or every one they see. */
export function amongOf(view: SessionsView): agent_sessions.Among {
  return view === "org" ? "visible" : "mine";
}

/** What Sessions shows, as the address bar holds it. */
export interface ListFilter {
  status: StatusFilter;
  view: SessionsView;
  /** An agent kind; empty for any. */
  kind: string;
  archived: boolean;
  /** Words the title holds. */
  query: string;
}

/** The filter the address bar names; `needs=you` reads as "Needs you" too. */
export function readListFilter(params: URLSearchParams): ListFilter {
  return {
    status: params.get("needs") === "you" ? "needs_you" : statusFilter(params.get("status")),
    view: params.get("view") === "org" ? "org" : "mine",
    kind: params.get("agent") ?? "",
    archived: params.get("archived") === "1",
    query: params.get("q") ?? "",
  };
}

/** The address bar's part of a filter: only what differs from the person's
 * own sessions in every status. */
export function listFilterParams(filter: ListFilter): Record<string, string> {
  const params: Record<string, string> = {};
  if (filter.view === "org") params.view = "org";
  if (filter.status !== "any") params.status = filter.status;
  if (filter.kind) params.agent = filter.kind;
  if (filter.archived) params.archived = "1";
  if (filter.query) params.q = filter.query;
  return params;
}

/** Whether the filter narrows the list past its view and its status. */
export function narrowed(filter: ListFilter): boolean {
  return filter.kind !== "" || filter.archived || filter.query.trim() !== "";
}

/** Whether a session shows in the org's view: an org-wide one, open to every
 * member. A private one never does, not even to one whose role lets them see
 * it for an audit: its creator keeps it on their own list, and its address
 * opens it. */
export function orgWide(session: Pick<agent_sessions.AgentSessionView, "visibility">): boolean {
  return session.visibility === "org_wide";
}

/** The roots whose tree holds a sub-agent parked on a person. */
export function treesNeedingYou(beneath: readonly agent_sessions.AgentSessionView[]): Set<string> {
  return new Set(beneath.filter((session) => session.parent_id !== null && session.archived_at === null && session.status === "parked" && session.park?.reason === "person").map((session) => session.root_id));
}

/** The sessions the list shows: the server read them in the view and the
 * status; here the org's view keeps the org-wide ones, and each narrows to
 * the agent, the archived, and the words of the title, case aside. "Needs
 * you" keeps one parked on a person, or whose tree holds a sub-agent that
 * is (`asking`, by root). A support conversation shows only under the
 * platform assistant's filter. */
export function listed(sessions: readonly agent_sessions.AgentSessionView[], filter: ListFilter, asking: ReadonlySet<string> = new Set()): agent_sessions.AgentSessionView[] {
  const words = filter.query.trim().toLowerCase();
  return sessions.filter(
    (session) =>
      (filter.view === "mine" || orgWide(session)) &&
      (filter.status !== "needs_you" || session.park?.reason === "person" || asking.has(session.id)) &&
      (filter.archived || session.archived_at === null) &&
      listedFor(session, filter.kind) &&
      (!words || session.title.toLowerCase().includes(words)),
  );
}

export interface SessionRow {
  id: string;
  title: string;
  kind: string;
  status: string;
  tone: Tone;
  startedAt: string;
  /** A sub-agent names the session that started it. */
  parentId: string | null;
  createdBy: string;
  visibility: attribution.Visibility;
  standing: Standing;
}

export function sessionRow(session: agent_sessions.AgentSessionView, me: string | null = null): SessionRow {
  const status = statusLine(session);
  return {
    id: session.id,
    title: session.title.trim() || "Untitled",
    kind: session.kind,
    status: status.label,
    tone: status.tone,
    startedAt: session.created_at,
    parentId: session.parent_id,
    createdBy: session.created_by,
    visibility: session.visibility,
    standing: standingOf(session, me),
  };
}

export const TITLE_MAX = 200;

export interface NewSessionDraft {
  title: string;
  kind: string;
  /** The agent project it starts in; empty for none. */
  agentProjectId: string;
}

/** Whether a session must start in an agent project. Every stack but a local one
 * refuses a session in none, as the API does, so no agent project's policy is
 * skipped by a session that names no agent project. */
export function agentProjectRequired(environment: string): boolean {
  return environment !== "local";
}

export const NO_AGENT_PROJECT = "A session starts in an agent project, and this org has none yet. Add one, then start the session.";

export interface AgentProjectChoice {
  options: { value: string; label: string }[];
  /** Why no session can start yet, when there is no agent project to choose. */
  problem: string | null;
}

/** The agent projects the form offers: a choice of one where an agent project is
 * required, with none to choose said as the reason nothing starts; locally,
 * "No agent project" as well. Null agent projects are not read yet. */
export function agentProjectChoice(agentProjects: readonly Pick<agent_projects.AgentProjectView, "id" | "name">[] | null, required: boolean): AgentProjectChoice {
  if (agentProjects === null) return { options: [], problem: null };
  const options = agentProjects.map((agentProject) => ({ value: agentProject.id, label: agentProject.name }));
  if (!required) return { options: [{ value: "", label: "No agent project" }, ...options], problem: null };
  if (options.length === 0) return { options: [], problem: NO_AGENT_PROJECT };
  return { options: [{ value: "", label: "Choose an agent project" }, ...options], problem: null };
}

/** The request a draft makes, or why it may not start yet. */
export function startRequest(
  draft: NewSessionDraft,
  agentProject: { required: boolean; count: number },
): { request: agent_sessions.StartAgentSessionRequest } | { problem: string } {
  const title = draft.title.trim();
  const kind = draft.kind.trim();
  if (!title) return { problem: "Give the session a title." };
  if (title.length > TITLE_MAX) return { problem: `A title is at most ${TITLE_MAX} characters.` };
  if (!kind) return { problem: "Name the kind of work it does." };
  if (agentProject.required && !draft.agentProjectId) return { problem: agentProject.count === 0 ? NO_AGENT_PROJECT : "Choose the agent project it works in." };
  return { request: { title, kind, ...(draft.agentProjectId ? { agent_project_id: draft.agentProjectId } : {}) } };
}

/** A time as the list and the page show it: the date and the minute. */
export function shortTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
