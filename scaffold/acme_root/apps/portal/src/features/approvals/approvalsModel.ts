// Pure: the calls the org's sessions hold for a person's decision, as the
// inbox lists them, oldest first. A call is decided on its session's page,
// where the session's own rules say who may decide it. No React, no fetch.
import type { ApprovalView } from "@acme/client";

export interface ApprovalRow {
  key: string;
  sessionId: string;
  tool: string;
  authorizationClass: string;
  requestedAt: string;
  principalId: string;
}

export function approvalRows(approvals: readonly ApprovalView[]): ApprovalRow[] {
  return approvals
    .map((approval) => ({
      key: `${approval.session_id}:${approval.seq}`,
      sessionId: approval.session_id,
      tool: approval.tool,
      authorizationClass: approval.authorization_class,
      requestedAt: approval.requested_at,
      principalId: approval.principal_id,
    }))
    .sort((a, b) => a.requestedAt.localeCompare(b.requestedAt));
}
