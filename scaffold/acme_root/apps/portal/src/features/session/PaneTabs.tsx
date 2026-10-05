// The platform's tabs of a session's right pane, in the shape a product's
// take (`SessionTab`): its workspace, one step, its changes, its evidence,
// its plan, its sub-agents, and its use. Each reads its own routes while it
// is drawn, and the page's reads and actions through `useSessionPage`.
import { useState } from "react";
import { Link } from "react-router-dom";
import type { SessionTab } from "../../app/product";
import {
  Button,
  Card,
  ChangesIcon,
  DataTable,
  ErrorText,
  EvidenceIcon,
  JsonView,
  Lightbox,
  LogView,
  Markdown,
  Muted,
  Pill,
  PlanIcon,
  StepIcon,
  SubAgentIcon,
  Table,
  TextArea,
  TextField,
  UsageIcon,
  WorkspaceIcon,
  type Column,
  type LightboxItem,
} from "../../design/kit";
import { useBounds, useChildren, useExecutions, useToolCalls, useUsage, useValidations } from "../../queries/agentSessions";
import { shortTime, sessionRow, type SessionRow } from "../sessions/sessionsModel";
import { changedFiles, delivered, latestPlan, stepOf } from "./paneModel";
import { runRow, usageLine, type RunRow } from "./sessionModel";
import { useSessionPage } from "./sessionContext";
import { Body, StateMark } from "./Timeline";
import { callLine, duration, editDiff, editOf, outputText, bodyKindOf } from "./timelineModel";

const count = (n: number) => n.toLocaleString("en-US");

/** What streams in its workspace now, and a person's hands on it: take
 * control, run a command, give it back. */
function WorkspaceTab() {
  const vm = useSessionPage();
  const [line, setLine] = useState("");
  const [summary, setSummary] = useState("");
  const runs = vm.session?.raw.status === "running" || vm.session?.raw.status === "pending";
  const streams = vm.live.flatMap((stream) => stream.runs.filter((run) => run.kind === "tool_output" || run.kind === "tool_input").map((run, index) => ({ stream, run, index })));
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
      <Card title="Live output" id="live">
        {!runs ? <Muted>No loop runs now. What its commands print shows here while it runs.</Muted> : null}
        {runs && streams.length === 0 ? <Muted>Nothing runs in its workspace at the moment.</Muted> : null}
        {streams.map(({ stream, run, index }) =>
          run.kind === "tool_output" ? (
            <LogView key={`${stream.stepId}-${index}`} output={run.text} label={`${run.tool ?? "Tool"} output`} />
          ) : (
            <pre key={`${stream.stepId}-${index}`} className="acme-code">
              {run.text}
            </pre>
          ),
        )}
      </Card>
      {vm.may?.takeControl ? (
        <Card title="Take control" id="control">
          <div className="acme-pane-stack">
            <Muted>The agent stands down and its loop waits. Your commands run on the host that holds its workspace, recorded as yours.</Muted>
            <div>
              <Button onClick={vm.takeControl}>Take control</Button>
            </div>
          </div>
        </Card>
      ) : null}
      {vm.may?.giveBack ? (
        <Card title="You have control" id="control">
          <div className="acme-pane-stack">
            <form
              className="acme-pane-row"
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
                <Muted>
                  <span data-command-state={vm.command.state}>
                    {vm.command.state}
                    {vm.command.exit_code !== null && vm.command.exit_code !== undefined ? `, exit ${vm.command.exit_code}` : ""}
                    {vm.command.refused ? `, refused: ${vm.command.refused}` : ""}
                    {vm.command.truncated ? ", output cut" : ""}
                  </span>
                </Muted>
                <LogView output={output} label="Command output" />
              </>
            ) : null}
            <form
              className="acme-pane-stack"
              aria-label="Give it back"
              onSubmit={(event) => {
                event.preventDefault();
                vm.giveBack(summary);
              }}
            >
              <TextArea label="What you did, for the agent to read" value={summary} onChange={setSummary} placeholder='e.g. "I fixed the import in conftest.py"' />
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

const DECISIONS: Record<string, string> = {
  pending: "Waits for a person's decision",
  approved: "Approved by a person",
  denied: "Denied by a person",
  expired: "The decision expired",
};

/** One call: what it was asked, what it answered, when, and who decided it. */
function StepTab() {
  const vm = useSessionPage();
  const calls = vm.slotSession?.calls ?? [];
  const call = stepOf(calls, vm.stepCall);
  const status = vm.session?.raw.status;
  const decisions = useToolCalls(vm.id, status === "running" || status === "pending" || status === "parked", call?.requestSeq != null);
  if (!call) return <Muted>No step yet. A click on a call in the timeline shows it here.</Muted>;
  const line = callLine(call, vm.gists);
  const made = call.requestSeq === null ? undefined : decisions.data?.find((each) => each.seq === call.requestSeq);
  const edit = editOf(call);
  const answer = outputText(call.output ?? call.liveOutput ?? "");
  const took = call.endedAt ? Math.max(0, (Date.parse(call.endedAt) - Date.parse(call.startedAt)) / 1000) : null;
  return (
    <section className="acme-step" aria-label="Step">
      <div className="acme-step-head">
        <StateMark state={call.state} />
        <strong>{line.gist.replace(/`/g, "")}</strong>
      </div>
      <dl className="acme-facts">
        <dt>Tool</dt>
        <dd>
          <code>{call.tool}</code>
        </dd>
        <dt>Asked</dt>
        <dd>{shortTime(call.startedAt)}</dd>
        <dt>Answered</dt>
        <dd>{call.endedAt ? `${shortTime(call.endedAt)}${took !== null ? `, after ${duration(Math.ceil(took))}` : ""}` : <Muted>not yet</Muted>}</dd>
        <dt>Decision</dt>
        <dd>{made?.decision ? DECISIONS[made.decision] ?? made.decision : call.requestSeq === null ? <Muted>no call made yet</Muted> : "None needed"}</dd>
        {call.failure ? (
          <>
            <dt>Failure</dt>
            <dd>{call.failure.replace(/_/g, " ")}</dd>
          </>
        ) : null}
      </dl>
      <h3 className="acme-step-heading">Asked</h3>
      {call.input ? <JsonView value={call.input} label="What it was asked" /> : <Muted>What it was asked is gone.</Muted>}
      {edit ? (
        <>
          <h3 className="acme-step-heading">Change</h3>
          <Body kind="diff" text={editDiff(edit.path, edit.removed, edit.added)} label="The change" />
        </>
      ) : null}
      <h3 className="acme-step-heading">Answer</h3>
      {answer ? <Body kind={bodyKindOf(answer)} text={answer} label="What it answered" /> : <Muted>{call.output === null ? "No answer yet." : "It answered nothing."}</Muted>}
    </section>
  );
}

/** Each file it edited, with its lines, then its branch, pull requests, and report. */
function ChangesTab() {
  const vm = useSessionPage();
  const files = changedFiles(vm.slotSession?.calls ?? []);
  const delivery = vm.delivery;
  return (
    <>
      <Card title="Files" id="files">
        {files.length === 0 ? <Muted>No file changed yet.</Muted> : null}
        <ul className="acme-files" aria-label="Changed files">
          {files.map((file) => (
            <li key={file.path}>
              <button type="button" className="acme-file" onClick={() => vm.openStep(file.lastCall)}>
                <code>{file.path}</code>
                <span className="acme-file-counts">
                  <span data-tone="added">+{file.added}</span> <span data-tone="removed">−{file.removed}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Delivery" id="delivery">
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
    </>
  );
}

/** The checks it ran, each with its outcome and where it ran, and its validations. */
function EvidenceTab() {
  const vm = useSessionPage();
  const executions = useExecutions(vm.id);
  const validations = useValidations(vm.id);
  const [shown, setShown] = useState<number | null>(null);
  const raw = executions.data ?? [];
  const items: LightboxItem[] = raw.map((run) => ({ title: `${run.check} ${run.check_version}`, content: <JsonView value={run} label="The run's record" /> }));
  const columns: Column<RunRow>[] = [
    { key: "check", header: "Check", cell: (run) => run.check, sortValue: (run) => run.check },
    { key: "purpose", header: "Purpose", cell: (run) => run.purpose, sortValue: (run) => run.purpose },
    { key: "outcome", header: "Outcome", cell: (run) => <Pill tone={run.tone}>{run.outcome}</Pill>, sortValue: (run) => run.outcome },
    { key: "provenance", header: "Provenance", cell: (run) => run.provenance, sortValue: (run) => run.provenance },
    { key: "cases", header: "Cases", cell: (run) => run.cases },
    { key: "seconds", header: "Took", cell: (run) => `${run.seconds.toFixed(1)} s`, sortValue: (run) => run.seconds },
    {
      key: "open",
      header: "",
      cell: (run) => (
        <Button tone="plain" onClick={() => setShown(raw.findIndex((each) => each.id === run.id))}>
          Record
        </Button>
      ),
    },
  ];
  return (
    <>
      <Card title="Runs" id="runs">
        {executions.isPending ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Runs" columns={columns} rows={raw.map(runRow)} rowKey={(run) => run.id} empty="No runs yet. A check the agent runs is recorded here." />
        )}
      </Card>
      <Card title="Validations" id="validations">
        {validations.data && validations.data.length === 0 ? <Muted>No validations yet.</Muted> : null}
        <ul className="acme-pane-list" aria-label="Validations">
          {(validations.data ?? []).map((validation) => (
            <li key={validation.id}>
              {validation.purpose} of <code>{validation.version.slice(0, 12)}</code> from {validation.source}: {validation.records.length}{" "}
              {validation.records.length === 1 ? "run" : "runs"}, results <code>{validation.results_sha256.slice(0, 12)}</code>
            </li>
          ))}
        </ul>
      </Card>
      {shown !== null && items[shown] ? <Lightbox items={items} index={shown} onIndex={setShown} onClose={() => setShown(null)} /> : null}
    </>
  );
}

/** The plan it wrote last. */
function PlanTab() {
  const vm = useSessionPage();
  const plan = latestPlan(vm.slotSession?.calls ?? []);
  if (!plan) return <Muted>No plan yet. A plan the agent writes shows here.</Muted>;
  return (
    <section className="acme-pane-plan" aria-label="Plan">
      <Muted>Written {shortTime(plan.at)}</Muted>
      <Markdown text={plan.text} />
    </section>
  );
}

const CHILD_COLUMNS: Column<SessionRow>[] = [
  { key: "title", header: "Title", cell: (child) => <Link to={`/sessions/${child.id}`}>{child.title}</Link>, sortValue: (child) => child.title },
  { key: "status", header: "Status", cell: (child) => <Pill tone={child.tone}>{child.status}</Pill>, sortValue: (child) => child.status },
  { key: "kind", header: "Agent", cell: (child) => child.kind, sortValue: (child) => child.kind },
  { key: "started", header: "Started", cell: (child) => shortTime(child.startedAt), sortValue: (child) => child.startedAt },
];

/** The sessions it started, and how far its tree may grow. */
function SubAgentsTab() {
  const vm = useSessionPage();
  const children = useChildren(vm.id);
  const bounds = useBounds(vm.id);
  const tree = bounds.data?.tree;
  return (
    <Card title="Sub-agents" id="children">
      <div className="acme-pane-stack">
        {tree ? (
          <Muted>
            Its tree has spawned {tree.size} of the {tree.count} sub-agents it may, at most {tree.height} deep.
          </Muted>
        ) : null}
        {children.isPending ? (
          <Muted>Loading</Muted>
        ) : (
          <DataTable label="Sub-agents" columns={CHILD_COLUMNS} rows={(children.data ?? []).map(sessionRow)} rowKey={(child) => child.id} empty="It started no sub-agents." />
        )}
      </div>
    </Card>
  );
}

/** Its model use, per model, and the limits its loop runs under. */
function UsageTab() {
  const vm = useSessionPage();
  const usage = useUsage(vm.id);
  const bounds = useBounds(vm.id);
  const loop = bounds.data?.loop;
  return (
    <>
      <Card title="Model use" id="usage">
        <div className="acme-pane-stack">
          <span>{usage.data ? usageLine(usage.data) : "Loading"}</span>
          {usage.data && usage.data.fills.length > 0 ? (
            <Table
              headers={["Model", "Calls", "In", "Out", "Thinking"]}
              rows={usage.data.fills.map((fill) => [<code key="fill">{fill.fill}</code>, count(fill.calls), count(fill.input), count(fill.output), count(fill.thinking)])}
            />
          ) : null}
        </div>
      </Card>
      <Card title="Loop limits" id="limits">
        {loop ? (
          <dl className="acme-facts">
            <dt>Step guard</dt>
            <dd>{count(loop.step_guard)} model calls before it asks a person</dd>
            <dt>Run time</dt>
            <dd>{duration(loop.run_time_seconds)} a run</dd>
            <dt>Error streak</dt>
            <dd>{loop.error_streak} failed calls in a row end the run</dd>
            <dt>Nudges</dt>
            <dd>{loop.nudges}</dd>
          </dl>
        ) : (
          <Muted>Loading</Muted>
        )}
      </Card>
    </>
  );
}

/** The platform's tabs, in the order "+" lists them. */
export const PLATFORM_TABS: SessionTab[] = [
  {
    id: "workspace",
    label: "Workspace",
    icon: <WorkspaceIcon />,
    tip: "What runs in its workspace; take control of it",
    offered: () => true,
    opensItself: (s) => s.running,
    render: () => <WorkspaceTab />,
  },
  {
    id: "step",
    label: "Step",
    icon: <StepIcon />,
    tip: "One call: what it was asked, what it answered, and when",
    offered: (s) => s.calls.length > 0,
    render: () => <StepTab />,
  },
  {
    id: "changes",
    label: "Changes",
    icon: <ChangesIcon />,
    tip: "The files it changed, its branch, its pull requests, and its report",
    offered: () => true,
    opensItself: (s) => delivered(s.calls),
    render: () => <ChangesTab />,
  },
  {
    id: "evidence",
    label: "Evidence",
    icon: <EvidenceIcon />,
    tip: "The checks it ran, and its validations",
    offered: () => true,
    render: () => <EvidenceTab />,
  },
  {
    id: "plan",
    label: "Plan",
    icon: <PlanIcon />,
    tip: "The plan it wrote last",
    offered: (s) => latestPlan(s.calls) !== null,
    render: () => <PlanTab />,
  },
  {
    id: "subagents",
    label: "Sub-agents",
    icon: <SubAgentIcon />,
    tip: "The sessions it started, and how far its tree may grow",
    offered: () => true,
    render: () => <SubAgentsTab />,
  },
  {
    id: "usage",
    label: "Usage",
    icon: <UsageIcon />,
    tip: "Its model use, and the limits of its loop",
    offered: () => true,
    render: () => <UsageTab />,
  },
];
