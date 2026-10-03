import type { FormEvent } from "react";
import { Button, ErrorText, SegmentedControl, Select, TextArea, TextField } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { PERIODS, type AutomationDraft } from "./automationsModel";

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
  const set = <K extends keyof AutomationDraft>(key: K) => (value: AutomationDraft[K]) => setDraft({ ...draft, [key]: value });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <form onSubmit={submit} style={grid} aria-label={label}>
      <TextField label="Name" value={draft.name} onChange={set("name")} />
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
          <TextField label="Every" value={draft.every} onChange={set("every")} />
          <Select
            label="Unit"
            value={draft.everyUnit}
            options={[
              { value: "minutes", label: "minutes" },
              { value: "hours", label: "hours" },
              { value: "days", label: "days" },
            ]}
            onChange={(value) => set("everyUnit")(value as AutomationDraft["everyUnit"])}
          />
        </div>
      ) : (
        <div style={row}>
          <TextField label="From integrations" placeholder="any; or names, by commas" value={draft.integrations} onChange={set("integrations")} />
          <TextField label="Arriving as" placeholder="any; or kinds, by commas" value={draft.arrivals} onChange={set("arrivals")} />
          <TextField label="Routed to" placeholder="any; or effects, by commas" value={draft.effects} onChange={set("effects")} />
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
          <TextField label="Session kind" value={draft.agentKind} onChange={set("agentKind")} />
          <TextField label="Session title" value={draft.title} onChange={set("title")} />
          {projectOptions.length > 0 ? <Select label="Project" value={draft.projectId} options={projectOptions} onChange={set("projectId")} /> : null}
        </div>
      ) : (
        <TextField label="Standing session id" value={draft.sessionId} onChange={set("sessionId")} />
      )}
      <TextArea label="Brief" value={draft.brief} onChange={set("brief")} />
      <div style={row}>
        <TextField label="Cost cap a period" placeholder="e.g. 5.00" value={draft.costCap} onChange={set("costCap")} />
        <TextField label="Cost cap a run" placeholder="e.g. 1.00" value={draft.runCap} onChange={set("runCap")} />
        <Select label="Period" value={draft.period} options={PERIODS.map((each) => ({ ...each }))} onChange={set("period")} />
        <TextField label="Firings a period" value={draft.rate} onChange={set("rate")} />
        <TextField label="Runs at once" value={draft.concurrency} onChange={set("concurrency")} />
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
