// All sessions: the org's sessions with filter chips (the status, whose,
// the agent, the archived), a filter by title, and "Load more". A session
// starts on Home.
import { Link } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, Muted, Page, Pill, SegmentedControl, Select, TextField, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime, STATUS_FILTERS, type ListFilter, type SessionRow } from "./sessionsModel";
import { useSessionsVm } from "./useSessionsVm";

const COLUMNS: Column<SessionRow>[] = [
  {
    key: "title",
    header: "Title",
    cell: (row) => <Link to={`/sessions/${row.id}`}>{row.title}</Link>,
    sortValue: (row) => row.title,
  },
  {
    key: "status",
    header: "Status",
    cell: (row) => <Pill tone={row.tone}>{row.status}</Pill>,
    sortValue: (row) => row.status,
  },
  { key: "kind", header: "Agent", cell: (row) => row.kind, sortValue: (row) => row.kind },
  {
    key: "started",
    header: "Started",
    cell: (row) => (
      <>
        {shortTime(row.startedAt)}
        {row.parentId ? <Muted> · a sub-agent</Muted> : null}
      </>
    ),
    sortValue: (row) => row.startedAt,
  },
];

const OWNERS: readonly { value: ListFilter["owner"]; label: string }[] = [
  { value: "everyone", label: "Everyone" },
  { value: "mine", label: "Mine" },
];

export function SessionsPage() {
  const vm = useSessionsVm();
  return (
    <Page title="All sessions" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The sessions could not be read.")}</Banner> : null}
      <Card>
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <div style={{ overflowX: "auto" }}>
            <SegmentedControl label="Status" value={vm.filter.status} options={STATUS_FILTERS} onChange={(status) => vm.setFilter({ status })} />
          </div>
          <div className="acme-filter-row">
            <SegmentedControl label="Whose sessions" value={vm.filter.owner} options={OWNERS} onChange={(owner) => vm.setFilter({ owner })} />
            <Select label="Agent" value={vm.filter.kind} options={vm.kinds} onChange={(kind) => vm.setFilter({ kind })} />
            <TextField label="Filter by title" placeholder="e.g. flaky test" value={vm.filter.query} onChange={(query) => vm.setFilter({ query })} />
            <label className="acme-check">
              <input type="checkbox" checked={vm.filter.archived} onChange={(event) => vm.setFilter({ archived: event.target.checked })} />
              Show archived
            </label>
          </div>
          {vm.rows === null ? (
            <Muted>Loading</Muted>
          ) : vm.rows.length === 0 && !vm.narrowed && !vm.hasMore ? (
            <Muted>
              No sessions yet. <Link to="/">Describe a task on Home.</Link>
            </Muted>
          ) : (
            <DataTable
              label="Sessions"
              columns={COLUMNS}
              rows={vm.rows}
              rowKey={(row) => row.id}
              empty={vm.hasMore ? "None on the pages read yet. Load more to look further." : "No session matches."}
            />
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
