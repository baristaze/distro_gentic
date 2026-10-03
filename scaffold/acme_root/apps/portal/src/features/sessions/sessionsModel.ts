// Pure: the tenant's sessions as the list shows them, the filters it offers,
// and what a new session needs before it may start. No React, no fetch.
import type { AgentSessionView, ProjectView, SessionStatus, StartSessionRequest } from "@acme/client";
import { statusLine, type Tone } from "../session/sessionModel";

export type StatusFilter = SessionStatus | "any";

export const STATUS_FILTERS: readonly { value: StatusFilter; label: string }[] = [
  { value: "any", label: "All" },
  { value: "running", label: "Running" },
  { value: "parked", label: "Parked" },
  { value: "pending", label: "Pending" },
  { value: "idle", label: "Idle" },
];

/** A filter from the address bar; anything else is every status. */
export function statusFilter(value: string | null): StatusFilter {
  return STATUS_FILTERS.some((filter) => filter.value === value) ? (value as StatusFilter) : "any";
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
