import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import type { common } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, ErrorText, Muted, Page, Pill, Select, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { AgentAutomationForm } from "./AgentAutomationForm";
import type { AgentAutomationRow } from "./agentAutomationsModel";
import { useAgentAutomationsVm } from "./useAgentAutomationsVm";

const COLUMNS: Column<AgentAutomationRow>[] = [
  { key: "name", header: "Name", cell: (row) => <Link to={`/agent-automations/${row.id}`}>{row.name}</Link>, sortValue: (row) => row.name },
  { key: "trigger", header: "When", cell: (row) => row.trigger },
  { key: "action", header: "What", cell: (row) => row.action },
  { key: "runsAs", header: "Runs as", cell: (row) => row.runsAs, sortValue: (row) => row.runsAs },
  {
    key: "state",
    header: "State",
    cell: (row) => <Pill tone={row.enabled ? "accent" : "plain"}>{row.enabled ? "on" : "off"}</Pill>,
    sortValue: (row) => (row.enabled ? "on" : "off"),
  },
];

export function AgentAutomationsPage() {
  const vm = useAgentAutomationsVm();
  const onGrant = (event: FormEvent) => {
    event.preventDefault();
    vm.submitGrant();
  };
  return (
    <Page title="Agent automations" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The agent automations could not be read.")}</Banner> : null}
      <Card title="The org's agent automations" id="agent_automations">
        {vm.rows === null ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Agent automations" columns={COLUMNS} rows={vm.rows} rowKey={(row) => row.id} empty="No agent automations yet." />
        )}
      </Card>
      {vm.mayWrite ? (
        <Card title="New agent automation" id="new">
          <AgentAutomationForm
            label="New agent automation"
            draft={vm.draft}
            setDraft={vm.setDraft}
            agentProjectOptions={vm.agentProjectOptions}
            problem={vm.problem}
            busy={vm.creating}
            submitLabel="Make the agent automation"
            onSubmit={vm.submit}
          />
        </Card>
      ) : null}
      <Card title="Agent automation principal" id="principal">
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <Muted>An agent automation that runs as the principal acts with the role granted here, never with its maker&apos;s.</Muted>
          {vm.principalError ? <ErrorText>{errorMessage(vm.principalError, "The principal could not be read.")}</ErrorText> : null}
          <p style={{ margin: 0 }} data-principal>
            {vm.principal === undefined
              ? "Loading"
              : vm.principal === null
                ? "No role is granted to the principal yet."
                : `The principal holds the role ${vm.principal.role}, granted by ${vm.principal.by}, ${shortTime(vm.principal.at)}.`}
          </p>
          {vm.mayGrant && vm.roles.length > 0 ? (
            <form onSubmit={onGrant} style={{ display: "flex", gap: tokens.space.sm, alignItems: "end", flexWrap: "wrap" }} aria-label="Grant the principal">
              <Select
                label="Role"
                value={vm.role}
                options={[{ value: "", label: "Pick a role" }, ...vm.roles.map((role) => ({ value: role, label: role }))]}
                onChange={(role) => vm.setRole(role as common.Role | "")}
              />
              <Button type="submit" disabled={vm.granting}>
                {vm.granting ? "Granting" : "Grant"}
              </Button>
              {vm.grantProblem ? <ErrorText>{vm.grantProblem}</ErrorText> : null}
            </form>
          ) : null}
        </div>
      </Card>
    </Page>
  );
}
