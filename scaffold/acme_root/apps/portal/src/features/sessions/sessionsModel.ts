// Pure: the tenant's sessions as the list shows them, the filters it offers,
// and what a new session needs before it may start. No React, no fetch.
import type { AgentSessionView, SessionStatus, StartSessionRequest } from "@acme/client";
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
}

/** The request a draft makes, or why it may not start yet. */
export function startRequest(draft: NewSessionDraft): { request: StartSessionRequest } | { problem: string } {
  const title = draft.title.trim();
  const kind = draft.kind.trim();
  if (!title) return { problem: "Give the session a title." };
  if (title.length > TITLE_MAX) return { problem: `A title is at most ${TITLE_MAX} characters.` };
  if (!kind) return { problem: "Name the kind of work it does." };
  return { request: { title, kind } };
}

/** A time as the list and the page show it: the date and the minute. */
export function shortTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
