import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, ConfirmDialog, ErrorText, Muted, Page, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { credentialLine } from "./agentProjectsModel";
import { useAgentProjectVm } from "./useAgentProjectVm";

const back = <Link to="/settings/agent-projects">← Agent projects</Link>;
const label = { color: tokens.color.muted } as const;
const value = { margin: 0 } as const;
const form = { display: "grid", gap: tokens.space.md } as const;

/** One agent project: its repository and record; for a member who manages the
 * org, a new name, the repository's read credential, and its removal. */
export function AgentProjectPage() {
  const { agentProjectId = "" } = useParams();
  const vm = useAgentProjectVm(agentProjectId);
  if (vm.missing) {
    return (
      <Page title="No agent project here" back={back}>
        <Card>
          <Muted>This org holds no agent project with this address. It may belong to another org, or it was removed.</Muted>
        </Card>
      </Page>
    );
  }
  if (!vm.agentProject) {
    return (
      <Page title="Agent project" back={back}>
        {vm.error ? <Banner>{errorMessage(vm.error, "The agent project could not be read.")}</Banner> : <Muted>Loading</Muted>}
      </Page>
    );
  }
  const agentProject = vm.agentProject;
  const onRename = (event: FormEvent) => {
    event.preventDefault();
    vm.submitRename();
  };
  const onCredential = (event: FormEvent) => {
    event.preventDefault();
    vm.submitCredential();
  };
  return (
    <Page title={agentProject.name} back={back} notice={<ProviderNotice />}>
      <Card title="Repository" id="repository">
        <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: `${tokens.space.sm} ${tokens.space.md}`, margin: 0 }}>
          <dt style={label}>Repository</dt>
          <dd style={value}>
            <code data-repository>{agentProject.repository}</code>
          </dd>
          <dt style={label}>Made</dt>
          <dd style={value}>
            {shortTime(agentProject.createdAt)} by {agentProject.createdBy}
          </dd>
          <dt style={label}>Changed</dt>
          <dd style={value}>
            {shortTime(agentProject.updatedAt)} by {agentProject.updatedBy}
          </dd>
        </dl>
      </Card>
      <Card title="Read credential" id="credential" info="Used only to fetch the repository">
        <div style={form}>
          <p data-credential style={{ margin: 0 }}>
            <Muted>{credentialLine(vm.saved ? { updated_at: vm.saved.at } : null, vm.saved?.by ?? "", shortTime)}</Muted>
          </p>
          {vm.mayManage ? (
            <form onSubmit={onCredential} style={form} aria-label="Read credential">
              <TextField
                label="User"
                value={vm.draft.username}
                autoComplete="off"
                placeholder="x-access-token"
                onChange={(username) => vm.setDraft({ ...vm.draft, username })}
              />
              <TextField
                label="Password or token"
                type="password"
                autoComplete="new-password"
                placeholder="A token that can read this repository"
                value={vm.draft.password}
                onChange={(password) => vm.setDraft({ ...vm.draft, password })}
              />
              {vm.credentialProblem ? <ErrorText>{vm.credentialProblem}</ErrorText> : null}
              <div>
                <Button type="submit" disabled={vm.savingCredential}>
                  {vm.savingCredential ? "Saving" : "Save the credential"}
                </Button>
              </div>
            </form>
          ) : null}
        </div>
      </Card>
      {vm.mayManage ? (
        <Card title="Name" id="name">
          <form onSubmit={onRename} style={form} aria-label="Rename">
            <TextField label="Name" placeholder="e.g. Storefront" value={vm.name} onChange={vm.setName} />
            {vm.renameProblem ? <ErrorText>{vm.renameProblem}</ErrorText> : null}
            <div>
              <Button type="submit" disabled={vm.renaming}>
                {vm.renaming ? "Renaming" : "Rename"}
              </Button>
            </div>
          </form>
        </Card>
      ) : null}
      {vm.mayManage ? (
        <Card title="Remove" id="remove">
          <div style={form}>
            <Muted>An agent project is removed only while no session belongs to it. Its credential goes with it.</Muted>
            {vm.removeProblem ? <ErrorText>{vm.removeProblem}</ErrorText> : null}
            <div>
              <Button tone="danger" onClick={vm.askRemove}>
                Remove the agent project
              </Button>
            </div>
          </div>
        </Card>
      ) : null}
      {vm.confirming ? (
        <ConfirmDialog
          title={`Remove ${agentProject.name}?`}
          confirmLabel="Remove"
          tone="danger"
          busy={vm.removing}
          onConfirm={vm.confirmRemove}
          onCancel={vm.cancelRemove}
        >
          The agent project and its credential are gone for good.
        </ConfirmDialog>
      ) : null}
    </Page>
  );
}
