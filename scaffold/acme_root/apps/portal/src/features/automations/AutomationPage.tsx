import { Link, useParams } from "react-router-dom";
import { AppNav } from "../../app/AppNav";
import { errorMessage } from "../../app/errorMessage";
import { Banner, Button, Card, Markdown, Muted, Page, Pill } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { ProviderNotice } from "../providers/ProviderNotice";
import { shortTime } from "../sessions/sessionsModel";
import { AutomationForm } from "./AutomationForm";
import { useAutomationVm } from "./useAutomationVm";

const back = <Link to="/automations">← Automations</Link>;
const label = { color: tokens.color.muted } as const;
const value = { margin: 0 } as const;

export function AutomationPage() {
  const { automationId = "" } = useParams();
  const vm = useAutomationVm(automationId);
  if (vm.missing) {
    return (
      <Page title="No automation here" back={back} nav={<AppNav />}>
        <Card>
          <Muted>This org holds no automation with this address. It may belong to another org.</Muted>
        </Card>
      </Page>
    );
  }
  if (!vm.automation) {
    return (
      <Page title="Automation" back={back} nav={<AppNav />}>
        {vm.error ? <Banner>{errorMessage(vm.error, "The automation could not be read.")}</Banner> : <Muted>Loading</Muted>}
      </Page>
    );
  }
  const automation = vm.automation;
  return (
    <Page title={automation.name} back={back} nav={<AppNav />} notice={<ProviderNotice />}>
      {vm.saved ? <Banner>The automation is saved.</Banner> : null}
      <Card title="What it does" id="automation">
        <dl
          data-automation
          style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: `${tokens.space.sm} ${tokens.space.md}`, margin: 0 }}
        >
          <dt style={label}>State</dt>
          <dd style={value}>
            <Pill tone={automation.enabled ? "accent" : "plain"}>{automation.enabled ? "on" : "off"}</Pill>
          </dd>
          <dt style={label}>When</dt>
          <dd style={value}>{automation.trigger}</dd>
          <dt style={label}>What</dt>
          <dd style={value}>{automation.action}</dd>
          <dt style={label}>Limits</dt>
          <dd style={value}>{automation.limits}</dd>
          <dt style={label}>Runs as</dt>
          <dd style={value}>{automation.runsAs}</dd>
          <dt style={label}>Its own events</dt>
          <dd style={value}>{automation.ownEvents ? "fire it" : "are ignored"}</dd>
          <dt style={label}>Made</dt>
          <dd style={value}>
            {shortTime(automation.createdAt)} by {automation.createdBy}
          </dd>
          <dt style={label}>Changed</dt>
          <dd style={value}>
            {shortTime(automation.updatedAt)} by {automation.updatedBy}
          </dd>
        </dl>
      </Card>
      <Card title="Brief" id="brief">
        <Markdown text={automation.brief} />
      </Card>
      {vm.mayWrite ? (
        <Card title="Edit" id="edit">
          {vm.draft ? (
            <div style={{ display: "grid", gap: tokens.space.md }}>
              <AutomationForm
                label="Edit automation"
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
            <Button onClick={vm.edit}>Edit the automation</Button>
          )}
        </Card>
      ) : null}
    </Page>
  );
}
