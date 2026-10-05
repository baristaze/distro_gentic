import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, ErrorText, Muted, Page, TextField, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import type { ProjectRow } from "./projectsModel";
import { useProjectsVm } from "./useProjectsVm";

const COLUMNS: Column<ProjectRow>[] = [
  { key: "name", header: "Name", cell: (row) => <Link to={`/settings/projects/${row.id}`}>{row.name}</Link>, sortValue: (row) => row.name },
  { key: "repository", header: "Repository", cell: (row) => <code>{row.repository}</code>, sortValue: (row) => row.repository },
  { key: "created", header: "Made", cell: (row) => shortTime(row.createdAt), sortValue: (row) => row.createdAt },
];

export function ProjectsPage() {
  const vm = useProjectsVm();
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    vm.submit();
  };
  return (
    <Page title="Projects" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The projects could not be read.")}</Banner> : null}
      {vm.mayManage ? (
        <Card title="New project" id="new">
          <form onSubmit={onSubmit} style={{ display: "grid", gap: tokens.space.md }} aria-label="New project">
            <TextField label="Name" placeholder="e.g. Storefront" value={vm.draft.name} onChange={(name) => vm.setDraft({ ...vm.draft, name })} />
            <TextField
              label="Repository"
              value={vm.draft.repository}
              placeholder="github.com/your-org/storefront"
              onChange={(repository) => vm.setDraft({ ...vm.draft, repository })}
            />
            <Muted style={{ fontSize: tokens.font.size.sm }}>A project is bound to its repository, which never moves.</Muted>
            {vm.problem ? <ErrorText>{vm.problem}</ErrorText> : null}
            <div>
              <Button type="submit" disabled={vm.creating}>
                {vm.creating ? "Making" : "Make the project"}
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
      <Card title="The org's projects" id="projects">
        {vm.rows === null ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Projects" columns={COLUMNS} rows={vm.rows} rowKey={(row) => row.id} empty="No projects yet." />
        )}
      </Card>
    </Page>
  );
}
