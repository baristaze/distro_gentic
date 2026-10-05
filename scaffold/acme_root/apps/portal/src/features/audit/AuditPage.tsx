import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, Muted, Page, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import type { AuditRow } from "./auditModel";
import { useAuditVm } from "./useAuditVm";

type Row = AuditRow & { actor: string };

const COLUMNS: Column<Row>[] = [
  { key: "seq", header: "#", cell: (row) => row.seq, sortValue: (row) => row.seq },
  { key: "what", header: "What", cell: (row) => <span title={row.kind}>{row.what}</span>, sortValue: (row) => row.kind },
  { key: "target", header: "Record", cell: (row) => <code>{row.targetId}</code> },
  { key: "actor", header: "By", cell: (row) => row.actor, sortValue: (row) => row.actor },
  { key: "at", header: "When", cell: (row) => shortTime(row.at), sortValue: (row) => row.at },
];

export function AuditPage() {
  const vm = useAuditVm();
  return (
    <Page title="Audit" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The audit could not be read.")}</Banner> : null}
      <Card title="What happened in the org" id="audit">
        <div style={{ display: "grid", gap: tokens.space.md }}>
          {vm.rows === null ? (
            <Muted>Loading</Muted>
          ) : (
            <DataTable label="Events" columns={COLUMNS} rows={vm.rows} rowKey={(row) => String(row.seq)} empty="Nothing has happened yet." />
          )}
          {vm.hasMore ? (
            <div>
              <Button tone="plain" onClick={vm.loadMore} disabled={vm.loadingMore}>
                {vm.loadingMore ? "Loading" : "Load older"}
              </Button>
            </div>
          ) : null}
        </div>
      </Card>
    </Page>
  );
}
