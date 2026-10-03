import { personName } from "../../app/recordModel";
import { useOrgApprovals } from "../../queries/approvals";
import { useAutomationPrincipal } from "../../queries/automations";
import { useUsers } from "../../queries/tenancy";
import { approvalRows } from "./approvalsModel";

/** Every call the org's sessions hold for a person, each with the principal
 * it runs for: a member, or the automation principal. Loading until every
 * page is read. */
export function useApprovalsVm() {
  const list = useOrgApprovals();
  const users = useUsers();
  const principal = useAutomationPrincipal();
  const rows = list.data && !list.isPending ? approvalRows(list.data) : null;
  return {
    rows: rows?.map((row) => ({ ...row, principal: personName(users.data, row.principalId, principal.data?.id) })) ?? null,
    error: list.error,
  };
}
