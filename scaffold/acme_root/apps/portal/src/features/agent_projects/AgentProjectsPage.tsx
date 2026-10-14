import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, ErrorText, Muted, Page, TextField, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import type { AgentProjectRow } from "./agentProjectsModel";
import { useAgentProjectsVm } from "./useAgentProjectsVm";

const COLUMNS: Column<AgentProjectRow>[] = [
  { key: "name", header: "Name", cell: (row) => <Link to={`/settings/agent-projects/${row.id}`}>{row.name}</Link>, sortValue: (row) => row.name },
  { key: "repository", header: "Repository", cell: (row) => <code>{row.repository}</code>, sortValue: (row) => row.repository },
  { key: "created", header: "Made", cell: (row) => shortTime(row.createdAt), sortValue: (row) => row.createdAt },
];

export function AgentProjectsPage() {
  const vm = useAgentProjectsVm();
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    vm.submit();
  };
  return (
    <Page title="Agent projects" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The agent projects could not be read.")}</Banner> : null}
      {vm.mayManage ? (
        <Card title="New agent project" id="new">
          <form onSubmit={onSubmit} style={{ display: "grid", gap: tokens.space.md }} aria-label="New agent project">
            <TextField label="Name" placeholder="e.g. Storefront" value={vm.draft.name} onChange={(name) => vm.setDraft({ ...vm.draft, name })} />
            <TextField
              label="Repository"
              value={vm.draft.repository}
              placeholder="github.com/your-org/storefront"
              onChange={(repository) => vm.setDraft({ ...vm.draft, repository })}
            />
            <Muted style={{ fontSize: tokens.font.size.sm }}>An agent project is bound to its repository, which never moves.</Muted>
            {vm.problem ? <ErrorText>{vm.problem}</ErrorText> : null}
            <div>
              <Button type="submit" disabled={vm.creating}>
                {vm.creating ? "Making" : "Make the agent project"}
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
      <Card title="The org's agent projects" id="agent_projects">
        {vm.rows === null ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Agent projects" columns={COLUMNS} rows={vm.rows} rowKey={(row) => row.id} empty="No agent projects yet." />
        )}
      </Card>
    </Page>
  );
}
