import type { FormEvent } from "react";
import { useSlot } from "../../app/slot";
import { Button, ErrorText, SegmentedControl, Select, TextArea, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { agentOptions, AS_SAVED, asSavedLine, periodOptions, type AutomationDraft } from "./automationsModel";

const grid = { display: "grid", gap: tokens.space.md } as const;
const row = { display: "grid", gap: tokens.space.md, gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))" } as const;

/** The fields of an automation, new or edited: its trigger, its action, its
 * limits, and whose authority it runs on. It draws the draft it is handed;
 * the view-model checks and sends it. */
export function AutomationForm({
  label,
  draft,
  setDraft,
  projectOptions,
  problem,
  busy,
  submitLabel,
  onSubmit,
}: {
  label: string;
  draft: AutomationDraft;
  setDraft: (draft: AutomationDraft) => void;
  projectOptions: { value: string; label: string }[];
  problem: string | null;
  busy: boolean;
  submitLabel: string;
  onSubmit: () => void;
}) {
  const agents = useSlot().agents;
  const agent = agents.find((each) => each.kind === draft.agentKind);
  const set = <K extends keyof AutomationDraft>(key: K) => (value: AutomationDraft[K]) => setDraft({ ...draft, [key]: value });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <form onSubmit={submit} style={grid} aria-label={label}>
      <TextField label="Name" placeholder="e.g. Nightly dependency update" value={draft.name} onChange={set("name")} />
      <SegmentedControl
        label="Trigger"
        value={draft.triggerKind}
        options={[
          { value: "schedule", label: "On a schedule" },
          { value: "event", label: "On an event" },
        ]}
        onChange={set("triggerKind")}
      />
      {draft.triggerKind === "schedule" ? (
        <div style={row}>
          {draft.everyUnit === AS_SAVED ? null : <TextField label="Every" placeholder="1" value={draft.every} onChange={set("every")} />}
          <Select
            label="Unit"
            value={draft.everyUnit}
            options={[
              { value: "minutes", label: "minutes" },
              { value: "hours", label: "hours" },
              { value: "days", label: "days" },
              ...(draft.savedEvery === null ? [] : [{ value: AS_SAVED, label: `every ${asSavedLine(draft.savedEvery)}` }]),
            ]}
            onChange={(value) => set("everyUnit")(value as AutomationDraft["everyUnit"])}
          />
        </div>
      ) : (
        <div style={row}>
          <TextField label="From integrations" placeholder="Any, or e.g. github" value={draft.integrations} onChange={set("integrations")} />
          <TextField label="Arriving as" placeholder="Any, or e.g. ticket, comment" value={draft.arrivals} onChange={set("arrivals")} />
          <TextField label="Routed to" placeholder="Any, or e.g. wake" value={draft.effects} onChange={set("effects")} />
        </div>
      )}
      <SegmentedControl
        label="Action"
        value={draft.actionKind}
        options={[
          { value: "start_session", label: "Start a session" },
          { value: "message_session", label: "Message a session" },
        ]}
        onChange={set("actionKind")}
      />
      {draft.actionKind === "start_session" ? (
        <div style={row}>
          <Select
            label="Agent"
            value={draft.agentKind}
            options={agentOptions(agents, draft.agentKind)}
            onChange={set("agentKind")}
            info={agent?.about ?? "The agent its sessions run"}
          />
          <TextField label="Session title" placeholder="e.g. Update dependencies" value={draft.title} onChange={set("title")} />
          {projectOptions.length > 0 ? <Select label="Project" value={draft.projectId} options={projectOptions} onChange={set("projectId")} /> : null}
        </div>
      ) : (
        <TextField label="Standing session id" placeholder="Paste a session's id from its address" value={draft.sessionId} onChange={set("sessionId")} />
      )}
      <TextArea
        label="Brief"
        placeholder='e.g. "Update minor versions, run the tests, and open a pull request if they pass"'
        value={draft.brief}
        onChange={set("brief")}
      />
      <div style={row}>
        <TextField label="Cost cap a period" placeholder="e.g. 5.00" value={draft.costCap} onChange={set("costCap")} />
        <TextField label="Cost cap a run" placeholder="e.g. 1.00" info="The most one run may spend" value={draft.runCap} onChange={set("runCap")} />
        <Select label="Period" value={draft.period} options={periodOptions(draft.savedPeriod)} onChange={set("period")} />
        <TextField label="Firings a period" placeholder="e.g. 10" value={draft.rate} onChange={set("rate")} />
        <TextField label="Runs at once" placeholder="e.g. 1" value={draft.concurrency} onChange={set("concurrency")} />
        <Select
          label="When limited"
          value={draft.queue}
          options={[
            { value: "no", label: "refuse the firing" },
            { value: "yes", label: "queue the firing" },
          ]}
          onChange={(value) => set("queue")(value as AutomationDraft["queue"])}
        />
      </div>
      <div style={row}>
        <Select
          label="Runs as"
          info="Whose permissions its sessions use"
          value={draft.runsAs}
          options={[
            { value: "creator", label: "its maker" },
            { value: "automation_principal", label: "the automation principal" },
          ]}
          onChange={(value) => set("runsAs")(value as AutomationDraft["runsAs"])}
        />
        <Select
          label="State"
          value={draft.enabled}
          options={[
            { value: "yes", label: "on" },
            { value: "no", label: "off" },
          ]}
          onChange={(value) => set("enabled")(value as AutomationDraft["enabled"])}
        />
      </div>
      {problem ? <ErrorText>{problem}</ErrorText> : null}
      <div>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
