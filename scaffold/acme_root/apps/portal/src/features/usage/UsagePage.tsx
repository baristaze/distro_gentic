import { AppNav } from "../../app/AppNav";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, Muted, Page, Pill, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import type { UsageRow } from "./usageModel";
import { useUsageVm } from "./useUsageVm";

const COLUMNS: Column<UsageRow>[] = [
  { key: "scope", header: "Budget", cell: (row) => row.scope, sortValue: (row) => row.scope },
  { key: "window", header: "Window", cell: (row) => row.window, sortValue: (row) => row.window },
  { key: "cost", header: "Cost", cell: (row) => row.cost },
  { key: "tokens", header: "Tokens", cell: (row) => row.tokens },
  {
    key: "used",
    header: "Used",
    cell: (row) => (row.used === null ? <Muted>no cap</Muted> : <Pill tone={row.used >= 100 ? "danger" : row.used >= 80 ? "plain" : "accent"}>{row.used}%</Pill>),
    sortValue: (row) => row.used ?? -1,
  },
];

export function UsagePage() {
  const vm = useUsageVm();
  return (
    <Page title="Usage" nav={<AppNav />} notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The usage could not be read.")}</Banner> : null}
      <Card title="Budgets" id="usage">
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <Muted style={{ fontSize: tokens.font.size.sm }}>
            A budget counts what settled calls spent and what open calls hold. A spent budget parks the sessions it bounds.
          </Muted>
          {vm.rows === null ? (
            <Muted>Loading</Muted>
          ) : (
            <DataTable label="Budgets" columns={COLUMNS} rows={vm.rows} rowKey={(row) => row.id} empty="The org has no budget yet." />
          )}
          {vm.hasMore ? (
            <div>
              <Button tone="plain" onClick={vm.loadMore} disabled={vm.loadingMore}>
                {vm.loadingMore ? "Loading" : "Load more"}
              </Button>
            </div>
          ) : null}
        </div>
      </Card>
    </Page>
  );
}
