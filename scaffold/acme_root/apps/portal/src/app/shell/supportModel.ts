// Pure: the conversation the support dock continues. Each person keeps one
// standing session with the support assistant, found again on each visit
// by the id this browser keeps for them in the org. The dock continues it
// only when the session reads back as theirs: another member's session,
// another kind, or an archived or deleted one is never read through the
// dock, and the next question starts a new conversation instead. The
// assistant answers in the request that asks it, so the dock shows its
// answer as the stream brings it, and says why an answer stopped short. The
// lists of work leave support conversations out. No React, no storage.
import type { agent_sessions } from "@acme/client";
import type { LiveStream } from "../../queries/live";

/** The agent the dock asks, whatever readers a product gives it: its loop
 * runs in the request that asks it. */
export const SUPPORT_KIND = "support_assistant";

/** The title a new support conversation starts under. */
export const SUPPORT_TITLE = "Support";

/** Whether a session is a support conversation: a session of the support
 * assistant, which only the dock asks. */
export function isSupport(session: Pick<agent_sessions.AgentSessionView, "kind" | "title">): boolean {
  return session.kind === SUPPORT_KIND;
}

/** Whether a list of work shows this session under its agent filter: the
 * session's own agent, or with none named, any session but a support
 * conversation. */
export function listedFor(session: Pick<agent_sessions.AgentSessionView, "kind" | "title">, kind: string): boolean {
  return kind ? session.kind === kind : !isSupport(session);
}

/** The key this browser keeps a person's conversation under: one per org
 * and person, so a member who signs in after another never gets theirs. */
export function conversationKey(org: string | null, user: string | null): string | null {
  return org && user ? `${org}/${user}` : null;
}

/** Whether the dock continues this session for this person. */
export function continues(session: Pick<agent_sessions.AgentSessionView, "kind" | "created_by" | "archived_at" | "deleted_at"> | undefined, me: string | null): boolean {
  return (
    session !== undefined &&
    me !== null &&
    session.created_by === me &&
    session.kind === SUPPORT_KIND &&
    session.archived_at === null &&
    session.deleted_at === null
  );
}

/** The answer as the stream brought it so far: a piece of text joins the
 * step it adds up to, after what that step already holds. */
export function heard(live: readonly LiveStream[], part: agent_sessions.QuestionTextEvent): LiveStream[] {
  const held = live.find((stream) => stream.stepId === part.agent_step_id);
  if (!held) {
    return [...live, { stepId: part.agent_step_id, last: part.n, dropped: false, runs: [{ kind: "text", tool: null, toolUseId: null, text: part.text }] }];
  }
  const runs = held.runs.map((run) => ({ ...run }));
  const tail = runs[runs.length - 1];
  if (tail && tail.kind === "text") tail.text += part.text;
  else runs.push({ kind: "text", tool: null, toolUseId: null, text: part.text });
  return live.map((stream) => (stream === held ? { ...held, last: part.n, runs } : stream));
}

/** What the dock says when a question's stream ends: nothing for a whole
 * answer, and why it stopped otherwise. Nothing waits in a request, so a
 * park ends the answer with its cause, and the next question runs anew. */
export function endLine(end: agent_sessions.QuestionEndEvent): string | null {
  if (end.end === "ended" && end.outcome === "succeeded") return null;
  if (end.end === "stale") return "Stopped: a later question took this conversation over.";
  if (end.cause) return `Stopped: ${end.cause}.`;
  return `Stopped: the answer ended ${end.outcome ?? end.end}.`;
}

/** What the dock says when a question's run failed in place of its end. */
export function failedLine(error: agent_sessions.QuestionErrorEvent): string {
  return `The answer failed: ${error.message}.`;
}
