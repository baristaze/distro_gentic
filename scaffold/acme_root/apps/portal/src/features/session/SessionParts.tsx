// The parts of a session's page, one per tab, and the header above them.
// Each draws what the view-model hands it; nothing here reads or decides.
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Banner,
  Button,
  Card,
  DataTable,
  DiffView,
  ErrorText,
  JsonView,
  Lightbox,
  LogView,
  Markdown,
  Muted,
  Pill,
  TextArea,
  TextField,
  parseJsonText,
  type Column,
  type LightboxItem,
} from "../../design/kit";
import { tokens } from "../../design/tokens";
import { shortTime, type SessionRow } from "../sessions/sessionsModel";
import type { RunRow, TimelineEntry, ToolCallRow } from "./sessionModel";
import type { SessionVm } from "./useSessionVm";

const row = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: tokens.space.sm } as const;
const stack = { display: "grid", gap: tokens.space.md } as const;
const small = { fontSize: tokens.font.size.sm } as const;

export function StepBody({ entry }: { entry: Pick<TimelineEntry, "body" | "bodyKind" | "title"> }): ReactNode {
  switch (entry.bodyKind) {
    case "markdown":
      return <Markdown text={entry.body} />;
    case "json":
      return <JsonView value={parseJsonText(entry.body)} label={entry.title} />;
    case "diff":
      return <DiffView text={entry.body} />;
    case "log":
      return <LogView output={entry.body} label={entry.title} />;
    case "none":
      return null;
  }
}

export function SessionHeader({ vm }: { vm: SessionVm }) {
  const session = vm.session!;
  const raw = session.raw;
  const [notes, setNotes] = useState<Record<number, string>>({});
  return (
    <Card id="session">
      <div style={stack}>
        <div style={{ ...row, ...small }} data-facts>
          <Pill tone={session.status.tone}>{session.status.label}</Pill>
          <Muted>
            {raw.kind} v{raw.kind_version} · started {shortTime(raw.created_at)}
          </Muted>
          {raw.parent_id ? (
            <Muted>
              · a sub-agent of <Link to={`/sessions/${raw.parent_id}`}>its parent</Link>
            </Muted>
          ) : null}
          {raw.root_id !== raw.id && raw.root_id !== raw.parent_id ? (
            <Muted>
              · in the tree of <Link to={`/sessions/${raw.root_id}`}>its root</Link>
            </Muted>
          ) : null}
        </div>
        {vm.park ? (
          <Banner>
            <div style={stack}>
              <span>
                {vm.park.reason} It is cleared by {vm.park.unlock}.
                {vm.park.retryAt ? ` It tries again by itself at ${shortTime(vm.park.retryAt)}.` : ""}
              </span>
              {vm.park.action === "resume" && vm.may?.resume ? (
                <div>
                  <Button onClick={() => vm.control("resume")}>Resume</Button>
                </div>
              ) : null}
              {vm.park.action === "give_back" && vm.may?.giveBack && vm.tab !== "live" ? (
                <div>
                  <Button onClick={() => vm.setTab("live")}>Go to the live view to give it back</Button>
                </div>
              ) : null}
            </div>
          </Banner>
        ) : null}
        {vm.asks.length > 0 ? (
          <div style={stack} aria-label="It asks you" role="group">
            {vm.asks.map((ask) => (
              <div key={ask.seq} style={stack} data-ask={ask.kind}>
                <span>
                  <strong>{ask.what}</strong> <Muted style={small}>since {shortTime(ask.at)}</Muted>
                </span>
                {vm.may?.send && ask.kind === "decision" ? (
                  <div style={row}>
                    <TextField label="Note (optional)" value={notes[ask.seq] ?? ""} onChange={(note) => setNotes({ ...notes, [ask.seq]: note })} />
                    <Button onClick={() => vm.decide(ask.seq, true, notes[ask.seq] ?? "")}>Approve</Button>
                    <Button tone="danger" onClick={() => vm.decide(ask.seq, false, notes[ask.seq] ?? "")}>
                      Deny
                    </Button>
                  </div>
                ) : null}
                {vm.may?.send && ask.kind === "unlock" ? (
                  <div>
                    <Button onClick={() => vm.control("unlock")}>Clear it</Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
        {vm.may ? (
          <div style={row}>
            {vm.may.pause ? (
              <Button tone="plain" onClick={() => vm.control("pause")}>
                Pause
              </Button>
            ) : null}
            {vm.may.cancel ? (
              <Button tone="plain" onClick={() => vm.control("cancel")}>
                Cancel the loop
              </Button>
            ) : null}
            {vm.may.compact ? (
              <Button tone="plain" onClick={() => vm.control("compact")}>
                Compact
              </Button>
            ) : null}
            <Muted style={{ ...small, marginLeft: "auto" }}>Ctrl K or ⌘K: every command</Muted>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

export function ThreadPart({ vm }: { vm: SessionVm }) {
  const [draft, setDraft] = useState("");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (draft.trim()) vm.send(draft.trim(), () => setDraft(""));
  };
  return (
    <Card title="Thread" id="thread">
      <div style={stack}>
        {vm.thread === null ? <Muted>Loading</Muted> : null}
        {vm.thread?.length === 0 ? <Muted>Nothing said yet. A message wakes the session.</Muted> : null}
        <ol style={{ ...stack, listStyle: "none", margin: 0, padding: 0 }} aria-label="Messages">
          {vm.thread?.map((entry) => (
            <li key={entry.seq} data-who={entry.who} style={{ display: "grid", gap: tokens.space.xs }}>
              <Muted style={small}>
                {entry.label} · {shortTime(entry.at)}
              </Muted>
              <Markdown text={entry.text} />
            </li>
          ))}
        </ol>
        {vm.may?.send ? (
          <form onSubmit={onSubmit} style={stack} aria-label="Send a message">
            <TextArea label="Message" value={draft} onChange={setDraft} />
            <div>
              <Button type="submit" disabled={vm.sending || !draft.trim()}>
                {vm.sending ? "Sending" : "Send"}
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </Card>
  );
}

/** Every step as a line of the timeline; a step's body is drawn only once
 * its entry is opened, so a long session draws its lines and not its
 * thousands of outputs. */
export function TimelinePart({ vm }: { vm: SessionVm }) {
  const entries = vm.timeline;
  const [opened, setOpened] = useState<ReadonlySet<number>>(() => new Set());
  const withBodies = useMemo(() => (entries ?? []).filter((entry) => entry.bodyKind !== "none"), [entries]);
  const bodyIndex = useMemo(() => new Map(withBodies.map((entry, index) => [entry.seq, index])), [withBodies]);
  const items: LightboxItem[] = useMemo(
    () => withBodies.map((entry) => ({ title: `${entry.seq}. ${entry.title}`, content: <StepBody entry={entry} /> })),
    [withBodies],
  );
  const toggle = (seq: number) =>
    setOpened((was) => {
      const next = new Set(was);
      if (!next.delete(seq)) next.add(seq);
      return next;
    });
  return (
    <Card title="Timeline" id="timeline">
      {entries === null ? <Muted>Loading</Muted> : null}
      {vm.stepsError ? <ErrorText>The history could not be read.</ErrorText> : null}
      {entries?.length === 0 ? <Muted>No steps yet.</Muted> : null}
      <ol className="acme-timeline" aria-label="Steps">
        {entries?.map((entry) => (
          <li key={entry.seq} data-type={entry.type} data-tone={entry.tone}>
            <div style={row}>
              <span className="acme-timeline-seq">{entry.seq}</span>
              <strong data-title>{entry.title}</strong>
              {entry.detail ? <Muted style={small}>{entry.detail}</Muted> : null}
              <Muted style={{ ...small, marginLeft: "auto" }}>{shortTime(entry.at)}</Muted>
              {entry.bodyKind !== "none" ? (
                <Button tone="plain" onClick={() => toggle(entry.seq)}>
                  {opened.has(entry.seq) ? "Hide" : "Show"}
                </Button>
              ) : null}
              {entry.bodyKind !== "none" && entry.bodyKind !== "markdown" ? (
                <Button tone="plain" onClick={() => vm.setShown(bodyIndex.get(entry.seq) ?? 0)}>
                  Enlarge
                </Button>
              ) : null}
            </div>
            {entry.bodyKind !== "none" && opened.has(entry.seq) ? (
              <div className="acme-timeline-body">
                <StepBody entry={entry} />
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      {vm.shown !== null && items.length > 0 ? (
        <Lightbox items={items} index={Math.min(vm.shown, items.length - 1)} onIndex={vm.setShown} onClose={() => vm.setShown(null)} />
      ) : null}
    </Card>
  );
}

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
              <TextField label="Command" value={line} onChange={setLine} placeholder="make test" />
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
              <TextArea label="What you did, for the agent to read" value={summary} onChange={setSummary} />
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
