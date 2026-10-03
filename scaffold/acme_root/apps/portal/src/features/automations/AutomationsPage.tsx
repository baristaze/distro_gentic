import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import type { Role } from "@acme/client";
import { AppNav } from "../../app/AppNav";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, ErrorText, Muted, Page, Pill, Select, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { AutomationForm } from "./AutomationForm";
import type { AutomationRow } from "./automationsModel";
import { useAutomationsVm } from "./useAutomationsVm";

const COLUMNS: Column<AutomationRow>[] = [
  { key: "name", header: "Name", cell: (row) => <Link to={`/automations/${row.id}`}>{row.name}</Link>, sortValue: (row) => row.name },
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

export function AutomationsPage() {
  const vm = useAutomationsVm();
  const onGrant = (event: FormEvent) => {
    event.preventDefault();
    vm.submitGrant();
  };
  return (
    <Page title="Automations" nav={<AppNav />} notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The automations could not be read.")}</Banner> : null}
      <Card title="The org's automations" id="automations">
        {vm.rows === null ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Automations" columns={COLUMNS} rows={vm.rows} rowKey={(row) => row.id} empty="No automations yet." />
        )}
      </Card>
      {vm.mayWrite ? (
        <Card title="New automation" id="new">
          <AutomationForm
            label="New automation"
            draft={vm.draft}
            setDraft={vm.setDraft}
            projectOptions={vm.projectOptions}
            problem={vm.problem}
            busy={vm.creating}
            submitLabel="Make the automation"
            onSubmit={vm.submit}
          />
        </Card>
      ) : null}
      <Card title="Automation principal" id="principal">
        <div style={{ display: "grid", gap: tokens.space.md }}>
          <Muted>An automation that runs as the principal acts with the role granted here, never with its maker&apos;s.</Muted>
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
                onChange={(role) => vm.setRole(role as Role | "")}
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
