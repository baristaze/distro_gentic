// The parts of a session's panel, one per tab: its tool calls, its
// evidence, its changes, its sub-agents, and its workspace. Each draws what
// the view-model hands it; nothing here reads or decides.
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Button,
  Card,
  DataTable,
  ErrorText,
  JsonView,
  Lightbox,
  LogView,
  Muted,
  Pill,
  TextArea,
  TextField,
  type Column,
  type LightboxItem,
} from "../../design/kit";
import { tokens } from "../../design/tokens";
import { shortTime, type SessionRow } from "../sessions/sessionsModel";
import type { RunRow, ToolCallRow } from "./sessionModel";
import type { SessionVm } from "./useSessionVm";

const row = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: tokens.space.sm } as const;
const stack = { display: "grid", gap: tokens.space.md } as const;
const small = { fontSize: tokens.font.size.sm } as const;

const TOOL_COLUMNS: Column<ToolCallRow>[] = [
  { key: "seq", header: "Step", cell: (call) => call.seq, sortValue: (call) => call.seq },
  { key: "tool", header: "Tool", cell: (call) => call.tool, sortValue: (call) => call.tool },
  { key: "state", header: "State", cell: (call) => <Pill tone={call.tone}>{call.state}</Pill>, sortValue: (call) => call.state },
  { key: "at", header: "Asked", cell: (call) => shortTime(call.requestedAt), sortValue: (call) => call.requestedAt },
];

export function ToolCallsPart({ vm }: { vm: SessionVm }) {
  return (
    <Card title="Tool calls" id="tools">
      {vm.toolCalls === null ? (
        <Muted>Loading</Muted>
      ) : (
        <DataTable label="Tool calls" columns={TOOL_COLUMNS} rows={vm.toolCalls} rowKey={(call) => String(call.seq)} empty="No tool calls yet." />
      )}
    </Card>
  );
}

export function EvidencePart({ vm }: { vm: SessionVm }) {
  const items: LightboxItem[] = vm.rawRuns.map((run) => ({ title: `${run.check} ${run.check_version}`, content: <JsonView value={run} label="The run's record" /> }));
  const columns: Column<RunRow>[] = [
    { key: "check", header: "Check", cell: (run) => run.check, sortValue: (run) => run.check },
    { key: "purpose", header: "Purpose", cell: (run) => run.purpose, sortValue: (run) => run.purpose },
    { key: "outcome", header: "Outcome", cell: (run) => <Pill tone={run.tone}>{run.outcome}</Pill>, sortValue: (run) => run.outcome },
    { key: "provenance", header: "Provenance", cell: (run) => run.provenance, sortValue: (run) => run.provenance },
    { key: "cases", header: "Cases", cell: (run) => run.cases },
    { key: "version", header: "Version", cell: (run) => <code>{run.version}</code> },
    { key: "seconds", header: "Took", cell: (run) => `${run.seconds.toFixed(1)} s`, sortValue: (run) => run.seconds },
    {
      key: "open",
      header: "",
      cell: (run) => (
        <Button tone="plain" onClick={() => vm.setShown(vm.rawRuns.findIndex((each) => each.id === run.id))}>
          Record
        </Button>
      ),
    },
  ];
  return (
    <>
      <Card title="Runs" id="runs">
        {vm.runs === null ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Runs" columns={columns} rows={vm.runs} rowKey={(run) => run.id} empty="No runs yet. A check the agent runs is recorded here." />
        )}
      </Card>
      <Card title="Validations" id="validations">
        {vm.validations.length === 0 ? <Muted>No validations yet.</Muted> : null}
        <ul style={{ ...stack, margin: 0, paddingLeft: tokens.space.md }} aria-label="Validations">
          {vm.validations.map((validation) => (
            <li key={validation.id}>
              {validation.purpose} of <code>{validation.version.slice(0, 12)}</code> from {validation.source}: {validation.records.length}{" "}
              {validation.records.length === 1 ? "run" : "runs"}, results <code>{validation.results_sha256.slice(0, 12)}</code>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Spend and bounds" id="usage">
        <div style={stack}>
          <span>{vm.usage ?? "Loading"}</span>
          {vm.bounds ? (
            <Muted style={small}>
              {vm.bounds.loop.step_guard} model calls before its step guard asks a person; {Math.round(vm.bounds.loop.run_time_seconds / 60)} minutes
              a run.
            </Muted>
          ) : null}
        </div>
      </Card>
      {vm.shown !== null && items[vm.shown] ? (
        <Lightbox items={items} index={vm.shown} onIndex={vm.setShown} onClose={() => vm.setShown(null)} />
      ) : null}
    </>
  );
}

export function ChangesPart({ vm }: { vm: SessionVm }) {
  const delivery = vm.delivery;
  return (
    <Card title="Changes" id="changes">
      {delivery === null ? (
        <Muted>Loading</Muted>
      ) : (
        <dl className="acme-facts">
          <dt>Branch</dt>
          <dd>{delivery.branch ? <code>{delivery.branch}</code> : <Muted>none yet</Muted>}</dd>
          <dt>Pull requests</dt>
          <dd>{delivery.pullRequests.length > 0 ? delivery.pullRequests.map((handle) => <code key={handle}>{handle} </code>) : <Muted>none yet</Muted>}</dd>
          {delivery.branches.length > 0 ? (
            <>
              <dt>Bound branches</dt>
              <dd>
                {delivery.branches.map((handle) => (
                  <code key={handle}>{handle} </code>
                ))}
              </dd>
            </>
          ) : null}
          <dt>Report</dt>
          <dd>{delivery.report ?? <Muted>no accepted result yet</Muted>}</dd>
        </dl>
      )}
    </Card>
  );
}

const CHILD_COLUMNS: Column<SessionRow>[] = [
  { key: "title", header: "Title", cell: (child) => <Link to={`/sessions/${child.id}`}>{child.title}</Link>, sortValue: (child) => child.title },
  { key: "status", header: "Status", cell: (child) => <Pill tone={child.tone}>{child.status}</Pill>, sortValue: (child) => child.status },
  { key: "kind", header: "Kind", cell: (child) => child.kind, sortValue: (child) => child.kind },
  { key: "started", header: "Started", cell: (child) => shortTime(child.startedAt), sortValue: (child) => child.startedAt },
];

export function ChildrenPart({ vm }: { vm: SessionVm }) {
  return (
    <Card title="Sub-agents" id="children">
      <div style={stack}>
        {vm.bounds ? (
          <Muted style={small}>
            Its tree has spawned {vm.bounds.tree.size} of the {vm.bounds.tree.count} sub-agents it may, at most {vm.bounds.tree.height} deep.
          </Muted>
        ) : null}
        {vm.children === null ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Sub-agents" columns={CHILD_COLUMNS} rows={vm.children} rowKey={(child) => child.id} empty="It started no sub-agents." />
        )}
      </div>
    </Card>
  );
}

export function LivePart({ vm }: { vm: SessionVm }) {
  const [line, setLine] = useState("");
  const [summary, setSummary] = useState("");
  const running = vm.session?.raw.status === "running";
  const output = vm.command
    ? vm.command.parts.length > 0
      ? vm.command.parts.map((part) => ({ stream: part.stream === "stderr" ? ("stderr" as const) : ("stdout" as const), text: part.text }))
      : [
          { stream: "stdout" as const, text: vm.command.stdout ?? "" },
          { stream: "stderr" as const, text: vm.command.stderr ?? "" },
        ]
    : [];
  return (
    <>
      <Card title="Live" id="live">
        <div style={stack}>
          {!running ? <Muted>No loop runs now. What it streams shows here while it runs.</Muted> : null}
          {running && vm.live.length === 0 ? <Muted>Nothing streams at the moment.</Muted> : null}
          {vm.live.map((stream) => (
            <div key={stream.stepId} style={stack} data-stream={stream.stepId}>
              {stream.dropped ? <Muted style={small}>Earlier parts were dropped; the step keeps them all.</Muted> : null}
              {stream.runs.map((run, index) =>
                run.kind === "tool_output" ? (
                  <LogView key={index} output={run.text} label={`${run.tool ?? "Tool"} output`} />
                ) : run.kind === "tool_input" ? (
                  <pre key={index} className="acme-code">
                    {run.text}
                  </pre>
                ) : (
                  <p key={index} style={{ margin: 0, whiteSpace: "pre-wrap", color: run.kind === "thinking" ? tokens.color.muted : undefined }}>
                    {run.text}
                  </p>
                ),
              )}
            </div>
          ))}
        </div>
      </Card>
      {vm.may?.takeControl ? (
        <Card title="Take control" id="control">
          <div style={stack}>
            <Muted>
              The agent stands down and its loop waits. Your commands run on the host that holds its workspace, recorded as yours.
            </Muted>
            <div>
              <Button onClick={vm.takeControl}>Take control</Button>
            </div>
          </div>
        </Card>
      ) : null}
      {vm.may?.giveBack ? (
        <Card title="You have control" id="control">
          <div style={stack}>
            <form
              style={row}
              aria-label="Run a command"
              onSubmit={(event) => {
                event.preventDefault();
                vm.runCommand(line, () => setLine(""));
              }}
            >
              <TextField label="Command" value={line} onChange={setLine} placeholder="e.g. pytest tests/test_dates.py -q" />
              <Button type="submit" disabled={!line.trim()}>
                Run
              </Button>
            </form>
            {vm.commandProblem ? <ErrorText>{vm.commandProblem}</ErrorText> : null}
            {vm.command ? (
              <>
                <Muted style={small}>
                  {vm.command.state}
                  {vm.command.exit_code !== null && vm.command.exit_code !== undefined ? `, exit ${vm.command.exit_code}` : ""}
                  {vm.command.refused ? `, refused: ${vm.command.refused}` : ""}
                  {vm.command.truncated ? ", output cut" : ""}
                </Muted>
                <LogView output={output} label="Command output" />
              </>
            ) : null}
            <form
              style={stack}
              aria-label="Give it back"
              onSubmit={(event) => {
                event.preventDefault();
                vm.giveBack(summary);
              }}
            >
              <TextArea
                label="What you did, for the agent to read"
                placeholder='e.g. "I fixed the import in conftest.py"'
                value={summary}
                onChange={setSummary}
              />
              <div>
                <Button type="submit" disabled={!summary.trim()}>
                  Give it back
                </Button>
              </div>
            </form>
          </div>
        </Card>
      ) : null}
    </>
  );
}
