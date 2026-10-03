import { Link } from "react-router-dom";
import { AppNav } from "../../app/AppNav";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Card, DataTable, Muted, Page, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import type { ApprovalRow } from "./approvalsModel";
import { useApprovalsVm } from "./useApprovalsVm";

type Row = ApprovalRow & { principal: string };

const COLUMNS: Column<Row>[] = [
  { key: "tool", header: "Call", cell: (row) => <code>{row.tool}</code>, sortValue: (row) => row.tool },
  { key: "class", header: "Class", cell: (row) => row.authorizationClass, sortValue: (row) => row.authorizationClass },
  { key: "principal", header: "For", cell: (row) => row.principal, sortValue: (row) => row.principal },
  { key: "requested", header: "Waiting since", cell: (row) => shortTime(row.requestedAt), sortValue: (row) => row.requestedAt },
  { key: "decide", header: "", cell: (row) => <Link to={`/sessions/${row.sessionId}`}>Decide on its session</Link> },
];

export function ApprovalsPage() {
  const vm = useApprovalsVm();
  return (
    <Page title="Approvals" nav={<AppNav />} notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The approvals could not be read.")}</Banner> : null}
      <Card title="Calls waiting on a person" id="approvals">
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <Muted style={{ fontSize: tokens.font.size.sm }}>Each call is decided on its session&apos;s page, where its context is.</Muted>
          {vm.rows === null ? (
            <Muted>Loading</Muted>
          ) : (
            <DataTable label="Approvals" columns={COLUMNS} rows={vm.rows} rowKey={(row) => row.key} empty="No call waits on a person." />
          )}
        </div>
      </Card>
    </Page>
  );
}
