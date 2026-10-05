import type { FormEvent } from "react";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, DataTable, ErrorText, Muted, Page, Pill, Select, TextField, type Column } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { providerName } from "../providers/outageModel";
import { shortTime } from "../sessions/sessionsModel";
import { fillLine, roleLabel, type KeyRow, type RoleRow } from "./modelsModel";
import { useModelsVm } from "./useModelsVm";

const STATES: Record<KeyRow["status"], { label: string; tone: "accent" | "plain" | "danger" }> = {
  live: { label: "live", tone: "accent" },
  rotated: { label: "rotated out", tone: "plain" },
  refused: { label: "refused", tone: "danger" },
};

const KEY_COLUMNS: Column<KeyRow>[] = [
  { key: "provider", header: "Provider", cell: (row) => row.provider, sortValue: (row) => row.provider },
  { key: "status", header: "State", cell: (row) => <Pill tone={STATES[row.status].tone}>{STATES[row.status].label}</Pill>, sortValue: (row) => row.status },
  { key: "added", header: "Added", cell: (row) => `${shortTime(row.addedAt)} by ${row.addedBy}`, sortValue: (row) => row.addedAt },
  { key: "used", header: "Last used", cell: (row) => (row.lastUsedAt ? shortTime(row.lastUsedAt) : "never"), sortValue: (row) => row.lastUsedAt ?? "" },
];

const form = { display: "grid", gap: tokens.space.md } as const;

export function ModelsPage() {
  const vm = useModelsVm();
  const roleColumns: Column<RoleRow>[] = [
    { key: "role", header: "Role", cell: (row) => roleLabel(row.role), sortValue: (row) => row.role },
    { key: "model", header: "Model", cell: (row) => (row.chosen ? fillLine(row.chosen) : <Muted>the matrix&apos;s choice</Muted>) },
  ];
  if (vm.mayManage) {
    roleColumns.push({
      key: "choose",
      header: "Choose",
      cell: (row) =>
        row.options.length === 0 ? (
          <Muted>none to choose</Muted>
        ) : (
          <div style={{ display: "flex", gap: tokens.space.sm, alignItems: "end", flexWrap: "wrap" }}>
            <Select
              label={`Model for ${roleLabel(row.role)}`}
              value={vm.picked[row.role] ?? ""}
              options={[{ value: "", label: "Pick a model" }, ...row.options.map((fill, index) => ({ value: String(index), label: fillLine(fill) }))]}
              onChange={(index) => vm.pick(row.role, index)}
            />
            <Button onClick={() => vm.chooseFor(row.role)} disabled={vm.roleBusy}>
              Choose
            </Button>
            {row.chosen ? (
              <Button tone="plain" onClick={() => vm.dropFor(row.role)} disabled={vm.roleBusy}>
                Use the matrix&apos;s
              </Button>
            ) : null}
          </div>
        ),
    });
  }
  return (
    <Page title="Models" notice={<ProviderNotice />}>
      {vm.error ? <Banner>{errorMessage(vm.error, "The models could not be read.")}</Banner> : null}
      <Card title="The org's own keys" id="keys">
        <div style={form}>
          <Muted style={{ fontSize: tokens.font.size.sm }}>
            A key is probed when it is saved, and its value is never shown again: only who added it, when, and when it was last used.
          </Muted>
          {vm.providers.map((each) => (
            <section key={each.provider} aria-label={providerName(each.provider)} data-provider={each.provider} style={form}>
              <strong>{providerName(each.provider)}</strong>
              <span data-key-line>{each.line ?? "Loading"}</span>
              {vm.mayManage ? (
                <form
                  style={form}
                  aria-label={`Key to ${providerName(each.provider)}`}
                  onSubmit={(event: FormEvent) => {
                    event.preventDefault();
                    vm.saveKey(each.provider);
                  }}
                >
                  <TextField
                    label={`New key to ${providerName(each.provider)}`}
                    type="password"
                    autoComplete="off"
                    value={each.draft}
                    onChange={(value) => vm.setDraft(each.provider, value)}
                  />
                  {each.problem ? <ErrorText>{each.problem}</ErrorText> : null}
                  <div>
                    <Button type="submit" disabled={vm.savingKey === each.provider}>
                      {vm.savingKey === each.provider ? "Saving" : "Save the key"}
                    </Button>
                  </div>
                </form>
              ) : null}
            </section>
          ))}
        </div>
      </Card>
      <Card title="Key history" id="history">
        {vm.keyRows === null ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Keys" columns={KEY_COLUMNS} rows={vm.keyRows} rowKey={(row) => row.id} empty="No key saved yet." />
        )}
      </Card>
      <Card title="Models by role" id="roles">
        <div style={form}>
          <Muted style={{ fontSize: tokens.font.size.sm }}>
            The org chooses a role&apos;s model only when it pays its providers on its own keys, and only among the models the matrix offers it.
          </Muted>
          {vm.roleProblem ? <ErrorText>{vm.roleProblem}</ErrorText> : null}
          {vm.roles === null ? (
            <Muted>Loading</Muted>
          ) : (
            <DataTable label="Roles" columns={roleColumns} rows={vm.roles} rowKey={(row) => row.role} empty="No role offers the org a choice." />
          )}
        </div>
      </Card>
    </Page>
  );
}
