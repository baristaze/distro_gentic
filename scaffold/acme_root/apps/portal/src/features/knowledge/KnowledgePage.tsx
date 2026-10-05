import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, ErrorText, Muted, Page, SegmentedControl, TextArea, TextField, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { STATUS_FILTERS, type EntryRow } from "./knowledgeModel";
import { useKnowledgeVm } from "./useKnowledgeVm";

const COLUMNS: Column<EntryRow>[] = [
  { key: "title", header: "Title", cell: (row) => <Link to={`/knowledge/${row.id}`}>{row.title}</Link>, sortValue: (row) => row.title },
  { key: "trigger", header: "Recalled by", cell: (row) => row.trigger, sortValue: (row) => row.trigger },
  { key: "updated", header: "Changed", cell: (row) => shortTime(row.updatedAt), sortValue: (row) => row.updatedAt },
];

const EMPTY: Record<string, string> = {
  reviewed: "No entry is kept yet.",
  suggested: "No suggestion waits for a review.",
  rejected: "No entry was rejected.",
};

export function KnowledgePage() {
  const vm = useKnowledgeVm();
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    vm.submit();
  };
  return (
    <Page title="Knowledge" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The knowledge could not be read.")}</Banner> : null}
      <Card title="The org's knowledge" id="knowledge">
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <Muted style={{ fontSize: tokens.font.size.sm }}>
            A session recalls a kept entry, as data, when every word that recalls it appears in what the session is about. An agent&apos;s suggestion waits
            for a person.
          </Muted>
          <SegmentedControl label="State" value={vm.status} options={STATUS_FILTERS} onChange={vm.setStatus} />
          {vm.rows === null ? (
            <Muted>Loading</Muted>
          ) : (
            <DataTable label="Entries" columns={COLUMNS} rows={vm.rows} rowKey={(row) => row.id} empty={EMPTY[vm.status] ?? ""} />
          )}
        </div>
      </Card>
      {vm.mayWrite ? (
        <Card title="New entry" id="new">
          <form onSubmit={onSubmit} style={{ display: "grid", gap: tokens.space.md }} aria-label="New entry">
            <TextField label="Title" value={vm.draft.title} onChange={(title) => vm.setDraft({ ...vm.draft, title })} />
            <TextField label="Recalled by" placeholder="words, by commas" value={vm.draft.trigger} onChange={(trigger) => vm.setDraft({ ...vm.draft, trigger })} />
            <TextArea label="What a session should know (Markdown)" value={vm.draft.text} onChange={(text) => vm.setDraft({ ...vm.draft, text })} />
            {vm.problem ? <ErrorText>{vm.problem}</ErrorText> : null}
            <div>
              <Button type="submit" disabled={vm.writing}>
                {vm.writing ? "Writing" : "Write the entry"}
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
    </Page>
  );
}
