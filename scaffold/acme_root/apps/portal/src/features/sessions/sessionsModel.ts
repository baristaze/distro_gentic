// Pure: the tenant's sessions as All sessions shows them, the filters it
// offers and keeps in the address bar, and what a new session needs before
// it may start. No React, no fetch.
import type { AgentSessionView, ProjectView, SessionStatus, StartSessionRequest } from "@acme/client";
import { listedFor } from "../../app/shell/supportModel";
import { statusLine, type Tone } from "../session/sessionModel";

/** A status, or the parked sessions that wait on a person: "Needs you". */
export type StatusFilter = SessionStatus | "any" | "needs_you";

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
export function serverStatus(filter: StatusFilter): SessionStatus | null {
  if (filter === "any") return null;
  return filter === "needs_you" ? "parked" : filter;
}

/** What All sessions shows, as the address bar holds it. */
export interface ListFilter {
  status: StatusFilter;
  owner: "everyone" | "mine";
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
    owner: params.get("owner") === "mine" ? "mine" : "everyone",
    kind: params.get("agent") ?? "",
    archived: params.get("archived") === "1",
    query: params.get("q") ?? "",
  };
}

/** The address bar's part of a filter: only what differs from showing every session. */
export function listFilterParams(filter: ListFilter): Record<string, string> {
  const params: Record<string, string> = {};
  if (filter.status !== "any") params.status = filter.status;
  if (filter.owner === "mine") params.owner = "mine";
  if (filter.kind) params.agent = filter.kind;
  if (filter.archived) params.archived = "1";
  if (filter.query) params.q = filter.query;
  return params;
}

/** Whether the filter narrows the list past its status. */
export function narrowed(filter: ListFilter): boolean {
  return filter.owner === "mine" || filter.kind !== "" || filter.archived || filter.query.trim() !== "";
}

/** The sessions the list shows: the server read them in the status; here
 * they narrow to whose they are, the agent, the archived, and the words of
 * the title, case aside. A support conversation shows only under the
 * platform assistant's filter. */
export function listed(sessions: readonly AgentSessionView[], filter: ListFilter, me: string | null): AgentSessionView[] {
  const words = filter.query.trim().toLowerCase();
  return sessions.filter(
    (session) =>
      (filter.status !== "needs_you" || session.park?.reason === "person") &&
      (filter.archived || session.archived_at === null) &&
      (filter.owner === "everyone" || session.created_by === me) &&
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
}

export function sessionRow(session: AgentSessionView): SessionRow {
  const status = statusLine(session);
  return {
    id: session.id,
    title: session.title.trim() || "Untitled",
    kind: session.kind,
    status: status.label,
    tone: status.tone,
    startedAt: session.created_at,
    parentId: session.parent_id,
  };
}

export const TITLE_MAX = 200;

export interface NewSessionDraft {
  title: string;
  kind: string;
  /** The project it starts in; empty for none. */
  projectId: string;
}

/** Whether a session must start in a project. Every stack but a local one
 * refuses a session in none, as the API does, so no project's policy is
 * skipped by a session that names no project. */
export function projectRequired(environment: string): boolean {
  return environment !== "local";
}

export const NO_PROJECT = "A session starts in a project, and this org has none yet. Add one, then start the session.";

export interface ProjectChoice {
  options: { value: string; label: string }[];
  /** Why no session can start yet, when there is no project to choose. */
  problem: string | null;
}

/** The projects the form offers: a choice of one where a project is
 * required, with none to choose said as the reason nothing starts; locally,
 * "No project" as well. Null projects are not read yet. */
export function projectChoice(projects: readonly Pick<ProjectView, "id" | "name">[] | null, required: boolean): ProjectChoice {
  if (projects === null) return { options: [], problem: null };
  const options = projects.map((project) => ({ value: project.id, label: project.name }));
  if (!required) return { options: [{ value: "", label: "No project" }, ...options], problem: null };
  if (options.length === 0) return { options: [], problem: NO_PROJECT };
  return { options: [{ value: "", label: "Choose a project" }, ...options], problem: null };
}

/** The request a draft makes, or why it may not start yet. */
export function startRequest(
  draft: NewSessionDraft,
  project: { required: boolean; count: number },
): { request: StartSessionRequest } | { problem: string } {
  const title = draft.title.trim();
  const kind = draft.kind.trim();
  if (!title) return { problem: "Give the session a title." };
  if (title.length > TITLE_MAX) return { problem: `A title is at most ${TITLE_MAX} characters.` };
  if (!kind) return { problem: "Name the kind of work it does." };
  if (project.required && !draft.projectId) return { problem: project.count === 0 ? NO_PROJECT : "Choose the project it works in." };
  return { request: { title, kind, ...(draft.projectId ? { project_id: draft.projectId } : {}) } };
}

/** A time as the list and the page show it: the date and the minute. */
export function shortTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
