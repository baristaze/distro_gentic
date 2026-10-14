import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, Markdown, Muted, Page, Pill } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { AgentAutomationForm } from "./AgentAutomationForm";
import { useAgentAutomationVm } from "./useAgentAutomationVm";

const back = <Link to="/agent-automations">← Agent automations</Link>;
const label = { color: tokens.color.muted } as const;
const value = { margin: 0 } as const;

export function AgentAutomationPage() {
  const { agentAutomationId = "" } = useParams();
  const vm = useAgentAutomationVm(agentAutomationId);
  if (vm.missing) {
    return (
      <Page title="No agent automation here" back={back}>
        <Card>
          <Muted>This org holds no agent automation with this address. It may belong to another org.</Muted>
        </Card>
      </Page>
    );
  }
  if (!vm.agentAutomation) {
    return (
      <Page title="Agent automation" back={back}>
        {vm.error ? <Banner>{errorMessage(vm.error, "The agent automation could not be read.")}</Banner> : <Muted>Loading</Muted>}
      </Page>
    );
  }
  const agentAutomation = vm.agentAutomation;
  return (
    <Page title={agentAutomation.name} back={back} notice={<ProviderNotice />}>
      {vm.saved ? <Banner>The agent automation is saved.</Banner> : null}
      <Card title="What it does" id="agent_automation">
        <dl
          data-agent-automation
          style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: `${tokens.space.sm} ${tokens.space.md}`, margin: 0 }}
        >
          <dt style={label}>State</dt>
          <dd style={value}>
            <Pill tone={agentAutomation.enabled ? "accent" : "plain"}>{agentAutomation.enabled ? "on" : "off"}</Pill>
          </dd>
          <dt style={label}>When</dt>
          <dd style={value}>{agentAutomation.trigger}</dd>
          <dt style={label}>What</dt>
          <dd style={value}>{agentAutomation.action}</dd>
          <dt style={label}>Limits</dt>
          <dd style={value}>{agentAutomation.limits}</dd>
          <dt style={label}>Runs as</dt>
          <dd style={value}>{agentAutomation.runsAs}</dd>
          <dt style={label}>Its own events</dt>
          <dd style={value}>{agentAutomation.ownEvents ? "fire it" : "are ignored"}</dd>
          <dt style={label}>Made</dt>
          <dd style={value}>
            {shortTime(agentAutomation.createdAt)} by {agentAutomation.createdBy}
          </dd>
          <dt style={label}>Changed</dt>
          <dd style={value}>
            {shortTime(agentAutomation.updatedAt)} by {agentAutomation.updatedBy}
          </dd>
        </dl>
      </Card>
      {agentAutomation.brief ? (
        <Card title="Brief" id="brief">
          <Markdown text={agentAutomation.brief} />
        </Card>
      ) : null}
      {vm.mayWrite ? (
        <Card title="Edit" id="edit">
          {vm.draft ? (
            <div style={{ display: "grid", gap: tokens.space.md }}>
              <AgentAutomationForm
                label="Edit agent automation"
                draft={vm.draft}
                setDraft={vm.setDraft}
                projectOptions={vm.projectOptions}
                problem={vm.problem}
                busy={vm.saving}
                submitLabel="Save"
                onSubmit={vm.submit}
              />
              <div>
                <Button tone="plain" onClick={vm.cancel}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button onClick={vm.edit}>Edit the agent automation</Button>
          )}
        </Card>
      ) : null}
    </Page>
  );
}
