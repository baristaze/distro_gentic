import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { AppNav } from "../../app/AppNav";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, Page, ErrorText, Muted, Pill, SegmentedControl, TextField, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { shortTime, STATUS_FILTERS, type SessionRow } from "./sessionsModel";
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
  { key: "kind", header: "Kind", cell: (row) => row.kind, sortValue: (row) => row.kind },
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

export function SessionsPage() {
  const vm = useSessionsVm();
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    vm.submit();
  };
  return (
    <Page title="Sessions" nav={<AppNav />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The sessions could not be read.")}</Banner> : null}
      {vm.mayWrite ? (
        <Card title="New session" id="new">
          <form onSubmit={onSubmit} style={{ display: "grid", gap: tokens.space.md }} aria-label="New session">
            <TextField label="Title" value={vm.draft.title} onChange={(title) => vm.setDraft({ ...vm.draft, title })} />
            <TextField
              label="Kind"
              value={vm.draft.kind}
              placeholder="The kind of work the product runs"
              onChange={(kind) => vm.setDraft({ ...vm.draft, kind })}
            />
            {vm.problem ? <ErrorText>{vm.problem}</ErrorText> : null}
            <div>
              <Button type="submit" disabled={vm.starting}>
                {vm.starting ? "Starting" : "Start"}
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
      <Card title="The org's sessions" id="sessions">
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <SegmentedControl label="Status" value={vm.filter} options={STATUS_FILTERS} onChange={vm.setFilter} />
          {vm.rows === null ? (
            <Muted>Loading</Muted>
          ) : (
            <DataTable
              label="Sessions"
              columns={COLUMNS}
              rows={vm.rows}
              rowKey={(row) => row.id}
              empty={vm.filter === "any" ? "No sessions yet." : "No session in this status."}
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
