import { personName } from "../../app/recordModel";
import { useAgentAutomationPrincipal } from "../../queries/agentAutomations";
import { useAuditEvents } from "../../queries/changeEvents";
import { useUsers } from "../../queries/tenancy";
import { auditRows } from "./auditModel";

/** The org's events from the newest, a page at a time, each with who
 * caused it: a member, or the agent automation principal its runs act as. */
export function useAuditVm() {
  const events = useAuditEvents();
  const users = useUsers();
  const principal = useAgentAutomationPrincipal();
  const actor = (id: string) => personName(users.data, id, principal.data?.id);
  return {
    rows: events.data ? auditRows(events.data).map((row) => ({ ...row, actor: actor(row.actorId) })) : null,
    error: events.error,
    hasMore: events.hasNextPage,
    loadingMore: events.isFetchingNextPage,
    loadMore: () => void events.fetchNextPage(),
  };
}
