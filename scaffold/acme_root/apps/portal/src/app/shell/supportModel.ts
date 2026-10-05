// Pure: the conversation the support dock continues. Each person keeps one
// standing session with the platform assistant, found again on each visit
// by the id this browser keeps for them in the org. The dock continues it
// only when the session reads back as theirs: another member's session,
// another kind, or an archived or deleted one is never read through the
// dock, and the next message starts a new conversation instead. No React,
// no storage.
import type { AgentSessionView } from "@acme/client";

/** The agent the dock talks to, whatever readers a product gives it. */
export const ASSISTANT_KIND = "platform_assistant";

/** The title a new support conversation starts under. */
export const SUPPORT_TITLE = "Support";

/** The key this browser keeps a person's conversation under: one per org
 * and person, so a member who signs in after another never gets theirs. */
export function conversationKey(org: string | null, user: string | null): string | null {
  return org && user ? `${org}/${user}` : null;
}

/** Whether the dock continues this session for this person. */
export function continues(session: Pick<AgentSessionView, "kind" | "created_by" | "archived_at" | "deleted_at"> | undefined, me: string | null): boolean {
  return (
    session !== undefined &&
    me !== null &&
    session.created_by === me &&
    session.kind === ASSISTANT_KIND &&
    session.archived_at === null &&
    session.deleted_at === null
  );
}
