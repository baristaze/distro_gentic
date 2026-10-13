// Sessions: the person's own first, the ones they made or take part in,
// and the org's to explore, where a member joins an org-wide session. Each
// view has filter chips (the status, the agent, the archived), a filter by
// title, and "Load more". A session starts on Home.
import { Link } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, Muted, Page, Pill, SegmentedControl, Select, TextField, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime, STATUS_FILTERS, VIEWS, type SessionRow } from "./sessionsModel";
import { useSessionsVm, type SessionsVm } from "./useSessionsVm";

function columns(vm: SessionsVm): Column<SessionRow>[] {
  const head: Column<SessionRow>[] = [
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
    { key: "starter", header: "Started by", cell: (row) => vm.starter(row), sortValue: (row) => vm.starter(row) },
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
  if (vm.filter.view === "mine")
    return [
      ...head,
      {
        key: "seen",
        header: "Seen by",
        cell: (row) =>
          row.visibility === "private" ? (
            <Pill title="Its creator and the people taking part">Private</Pill>
          ) : (
            <Muted>{row.standing === "joined" ? "The org · joined" : "The org"}</Muted>
          ),
        sortValue: (row) => row.visibility,
      },
    ];
  return [
    ...head,
    {
      key: "join",
      header: "You",
      cell: (row) =>
        row.standing === "none" ? (
          <Button tone="plain" onClick={() => vm.join(row)} disabled={vm.joining === row.id}>
            {vm.joining === row.id ? "Joining" : "Join"}
          </Button>
        ) : (
          <Muted>{row.standing === "made" ? "Yours" : "Joined"}</Muted>
        ),
      sortValue: (row) => row.standing,
    },
  ];
}

export function SessionsPage() {
  const vm = useSessionsVm();
  const mine = vm.filter.view === "mine";
  return (
    <Page title="Sessions" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The sessions could not be read.")}</Banner> : null}
      <Card>
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <SegmentedControl large label="Whose sessions" value={vm.filter.view} options={VIEWS} onChange={(view) => vm.setFilter({ view })} />
          <Muted>
            {mine
              ? "The sessions you started or joined. A private one is seen by you and the people taking part."
              : "Every org-wide session of the org. Join one to take part: your messages reach its agent as suggestions to whoever steers it."}
          </Muted>
          <div style={{ overflowX: "auto" }}>
            <SegmentedControl label="Status" value={vm.filter.status} options={STATUS_FILTERS} onChange={(status) => vm.setFilter({ status })} />
          </div>
          <div className="acme-filter-row">
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
            mine ? (
              <Muted>
                No sessions yet. <Link to="/">Describe a task on Home</Link>, or join one of the org's.
              </Muted>
            ) : (
              <Muted>The org has no org-wide session yet.</Muted>
            )
          ) : (
            <DataTable
              label={mine ? "Your sessions" : "The org's sessions"}
              columns={columns(vm)}
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
