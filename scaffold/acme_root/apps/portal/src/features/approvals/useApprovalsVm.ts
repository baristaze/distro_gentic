import { personName } from "../../app/recordModel";
import { useOrgApprovals } from "../../queries/approvals";
import { useUsers } from "../../queries/tenancy";
import { approvalRows } from "./approvalsModel";

/** The calls the org's sessions hold for a person, a page of parked
 * sessions at a time, each with the principal it runs for. */
export function useApprovalsVm() {
  const list = useOrgApprovals();
  const users = useUsers();
  return {
    rows: list.data ? approvalRows(list.data).map((row) => ({ ...row, principal: personName(users.data, row.principalId) })) : null,
    error: list.error,
    hasMore: list.hasNextPage,
    loadingMore: list.isFetchingNextPage,
    loadMore: () => void list.fetchNextPage(),
  };
}
