import { personName } from "../../app/recordModel";
import { useAuditEvents } from "../../queries/events";
import { useUsers } from "../../queries/tenancy";
import { auditRows } from "./auditModel";

/** The org's events from the first, a page at a time, each with who caused
 * it. */
export function useAuditVm() {
  const events = useAuditEvents();
  const users = useUsers();
  return {
    rows: events.data ? auditRows(events.data).map((row) => ({ ...row, actor: personName(users.data, row.actorId) })) : null,
    error: events.error,
    hasMore: events.hasNextPage,
    loadingMore: events.isFetchingNextPage,
    loadMore: () => void events.fetchNextPage(),
  };
}
