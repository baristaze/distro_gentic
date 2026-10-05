// A session's history as a chat: each entry the timeline model makes, drawn
// as its row, the status line under the last, and the outline on its edge.
// Nothing here reads or decides: a row folds or opens, a call's line opens
// it in the pane, and a card's button calls the view-model. What a model or
// a sub-agent wrote is drawn as text or as the kit's Markdown, never as HTML.
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { Link } from "react-router-dom";
import {
  AskIcon,
  Button,
  CheckIcon,
  ChevronRightIcon,
  CopyIcon,
  DiffView,
  FailedIcon,
  HeldIcon,
  IconButton,
  JsonView,
  JumpIcon,
  LogView,
  Markdown,
  Muted,
  OutlineIcon,
  ParentIcon,
  PlanIcon,
  PullRequestIcon,
  ReportIcon,
  ResultIcon,
  SpinnerIcon,
  SubAgentIcon,
  TextField,
  ValidationIcon,
  parseJsonText,
  type KitIcon,
} from "../../design/kit";
import { shortTime } from "../sessions/sessionsModel";
import { CUT_NOTE, duration, type BodyKind, type Call, type CallLine, type CallState, type CardKind, type ChildPhase, type Entry, type OutlineMark, type ThoughtEntry } from "./timelineModel";
import type { SessionVm } from "./useSessionVm";

/** A line's words, a `quoted` run drawn as code. */
function Gist({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/);
  return (
    <>
      {parts.map((part, index) =>
        part.length > 2 && part.startsWith("`") && part.endsWith("`") ? <code key={index}>{part.slice(1, -1)}</code> : part,
      )}
    </>
  );
}

export function Body({ kind, text, label }: { kind: BodyKind; text: string; label: string }): ReactNode {
  switch (kind) {
    case "markdown":
      return <Markdown text={text} />;
    case "json":
      return <JsonView value={parseJsonText(text)} label={label} />;
    case "diff":
      return <DiffView text={text} />;
    case "log":
      return <LogView output={text} label={label} />;
    case "none":
      return null;
  }
}

const STATE_WORDS: Record<CallState, string> = {
  asked: "Asked",
  held: "Waits for a decision",
  running: "Running",
  done: "Answered",
  failed: "Failed",
  denied: "Denied",
  stopped: "Stopped",
};

export function StateMark({ state }: { state: CallState }) {
  const Icon = state === "done" ? CheckIcon : state === "held" ? HeldIcon : state === "failed" || state === "denied" ? FailedIcon : state === "stopped" ? FailedIcon : SpinnerIcon;
  return (
    <span className="acme-call-state" data-state={state} role="img" aria-label={STATE_WORDS[state]} title={STATE_WORDS[state]}>
      <Icon size={14} />
    </span>
  );
}

/** Opens a call in the session's pane. */
type OnOpen = (call: Call) => void;

/** One call: its state and its line, which opens it in the pane, and the
 * chevron that shows its answer inline. A running call shows what it
 * streams without a click. */
function CallRow({ line, onOpen }: { line: CallLine; onOpen: OnOpen }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const has = line.bodyKind !== "none";
  const shown = has && (open ?? (line.call.output === null && line.call.liveOutput !== null));
  return (
    <div className="acme-call" data-tool={line.call.tool} data-state={line.call.state}>
      <div className="acme-call-head">
        <button type="button" className="acme-call-line" title="Open this step in the panel" onClick={() => onOpen(line.call)}>
          <StateMark state={line.call.state} />
          <span className="acme-call-gist">
            <Gist text={line.gist} />
          </span>
        </button>
        {has ? (
          <button
            type="button"
            className="acme-call-fold"
            aria-expanded={shown}
            aria-label={shown ? "Hide its answer" : "Show its answer"}
            title={shown ? "Hide its answer" : "Show its answer"}
            onClick={() => setOpen(!shown)}
          >
            <ChevronRightIcon size={14} className="acme-fold-mark" />
          </button>
        ) : null}
      </div>
      {shown ? (
        <div className="acme-call-body">
          <Body kind={line.bodyKind} text={line.body} label={line.gist} />
          {line.cut ? <p className="acme-cut-note">{CUT_NOTE}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

/** "Thought for 4s", folded; "Thinking…", open while it streams. */
function ThoughtRow({ entry }: { entry: ThoughtEntry }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = !!entry.text && (open ?? entry.live);
  const label = entry.live ? "Thinking…" : entry.seconds !== null ? `Thought for ${duration(entry.seconds)}` : "Thought";
  return (
    <div className="acme-thought" data-live={entry.live || undefined}>
      <button type="button" className="acme-fold-line" aria-expanded={entry.text ? shown : undefined} disabled={!entry.text} onClick={() => setOpen(!shown)}>
        {entry.text ? <ChevronRightIcon size={14} className="acme-fold-mark" /> : null}
        <span>{label}</span>
      </button>
      {shown ? (
        <div className="acme-thought-text">
          <Markdown text={entry.text} />
        </div>
      ) : null}
    </div>
  );
}

function WorkBlock({ entry, onOpen }: { entry: Extract<Entry, { kind: "work" }>; onOpen: OnOpen }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const shown = open ?? entry.running;
  const label = `${entry.running ? "Working for" : "Worked for"} ${duration(entry.seconds)} · ${entry.steps} ${entry.steps === 1 ? "step" : "steps"}`;
  return (
    <div className="acme-work" data-running={entry.running || undefined}>
      <button type="button" className="acme-fold-line" aria-expanded={shown} onClick={() => setOpen(!shown)}>
        <ChevronRightIcon size={14} className="acme-fold-mark" />
        <span>{label}</span>
        {entry.running ? <SpinnerIcon size={14} className="acme-spin" /> : null}
      </button>
      {shown ? (
        <div className="acme-work-items">
          {entry.items.map((item) => (item.kind === "call" ? <CallRow key={item.key} line={item} onOpen={onOpen} /> : <ThoughtRow key={item.key} entry={item} />))}
        </div>
      ) : null}
    </div>
  );
}

function ActionCard({ entry, vm }: { entry: Extract<Entry, { kind: "action" }>; vm: SessionVm }) {
  const [denying, setDenying] = useState(false);
  const [note, setNote] = useState("");
  const seq = entry.line.call.requestSeq;
  return (
    <section className="acme-tcard" data-card="action" aria-label="Action required">
      <header className="acme-tcard-head">
        <HeldIcon size={16} />
        <strong>Action required</strong>
        <Muted>
          {entry.line.call.tool}
          {entry.authorizationClass ? ` · ${entry.authorizationClass.replace(/_/g, " ")}` : ""}
        </Muted>
      </header>
      <CallRow line={entry.line} onOpen={vm.openCall} />
      {vm.may?.send && seq !== null ? (
        <div className="acme-tcard-actions">
          {denying ? (
            <>
              <TextField label="Why" value={note} onChange={setNote} placeholder='Tell the agent why, e.g. "Leave the migrations alone"' />
              <Button tone="danger" disabled={vm.deciding} onClick={() => vm.decide(seq, false, note)}>
                Deny
              </Button>
              <Button tone="plain" onClick={() => setDenying(false)}>
                Back
              </Button>
            </>
          ) : (
            <>
              <Button disabled={vm.deciding} onClick={() => vm.decide(seq, true, "")}>
                Approve
              </Button>
              <Button tone="plain" onClick={() => setDenying(true)}>
                Deny…
              </Button>
            </>
          )}
        </div>
      ) : (
        <Muted>A member who may write decides it.</Muted>
      )}
    </section>
  );
}

function AskCard({ entry, vm }: { entry: Extract<Entry, { kind: "ask" }>; vm: SessionVm }) {
  return (
    <section className="acme-tcard" data-card="ask" data-open={entry.open || undefined} aria-label="The agent asks">
      <header className="acme-tcard-head">
        <AskIcon size={16} />
        <strong>The agent asks</strong>
      </header>
      <Markdown text={entry.question} />
      {entry.unlock !== null ? (
        vm.may?.send ? (
          <div className="acme-tcard-actions">
            <Button onClick={() => vm.control("unlock")}>Clear it</Button>
          </div>
        ) : null
      ) : (
        <Muted>{entry.open ? "Answer it in the box below." : "Answered."}</Muted>
      )}
    </section>
  );
}

const CARDS: Record<CardKind, { label: string; Icon: KitIcon }> = {
  plan: { label: "Plan", Icon: PlanIcon },
  pull_request: { label: "Pull request", Icon: PullRequestIcon },
  validation: { label: "Validation", Icon: ValidationIcon },
  result: { label: "Result", Icon: ResultIcon },
};

function DeliveryCard({ entry }: { entry: Extract<Entry, { kind: "card" }> }) {
  const { label, Icon } = CARDS[entry.card];
  const [open, setOpen] = useState(false);
  const inline = entry.card === "plan" || entry.card === "pull_request";
  const bodyKind: BodyKind = inline ? "markdown" : parseJsonText(entry.body) !== undefined ? "json" : "log";
  return (
    <section className="acme-tcard" data-card={entry.card} aria-label={label}>
      <header className="acme-tcard-head">
        <Icon size={16} />
        <span className="acme-tcard-kind">{label}</span>
        <StateMark state={entry.line.call.state} />
      </header>
      {entry.title !== label ? <strong className="acme-tcard-title">{entry.title}</strong> : null}
      {entry.facts.length > 0 ? (
        <ul className="acme-tcard-facts">
          {entry.facts.map((fact) => (
            <li key={fact}>{/^https?:\/\//.test(fact) ? <a href={fact}>{fact}</a> : fact}</li>
          ))}
        </ul>
      ) : null}
      {entry.body && inline ? (
        <div className="acme-tcard-body">
          <Markdown text={entry.body} />
          {entry.cut ? <p className="acme-cut-note">{CUT_NOTE}</p> : null}
        </div>
      ) : null}
      {entry.body && !inline ? (
        <>
          <button type="button" className="acme-fold-line" aria-expanded={open} onClick={() => setOpen(!open)}>
            <ChevronRightIcon size={14} className="acme-fold-mark" />
            <span>Its answer</span>
          </button>
          {open ? <Body kind={bodyKind} text={entry.body} label={label} /> : null}
        </>
      ) : null}
    </section>
  );
}

const PHASE_DOTS: Record<ChildPhase, string> = { needs_you: "needs", working: "running", waiting: "waiting", done: "done" };

/** The sub-agents one response started: a row each, live until it ends. */
function SubAgentsCard({ entry }: { entry: Extract<Entry, { kind: "subagents" }> }) {
  return (
    <section className="acme-tcard" data-card="subagents" aria-label={entry.title}>
      <header className="acme-tcard-head">
        <SubAgentIcon size={16} />
        <strong>{entry.title}</strong>
      </header>
      <ul className="acme-subagents" aria-label="Its sub-agents">
        {entry.rows.map((row) => (
          <li key={row.key} className="acme-subagent" data-phase={row.phase ?? undefined}>
            <span className="acme-row-dot" data-dot={row.phase ? PHASE_DOTS[row.phase] : "waiting"} aria-hidden="true" />
            <span className="acme-subagent-main">
              <span className="acme-subagent-title">{row.title}</span>
              <span className="acme-subagent-doing">
                <span className="acme-subagent-agent">{row.agent}</span>
                <span className="acme-subagent-words">
                  <Gist text={row.activity ?? row.words} />
                </span>
              </span>
            </span>
            {row.seconds !== null ? <span className="acme-subagent-time">{duration(row.seconds)}</span> : null}
            {row.childId ? (
              <Link className="acme-subagent-open" to={`/sessions/${row.childId}`} aria-label={`Open ${row.title}`}>
                Open
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A sub-agent's report: how its loop stands, its last answer folded, and
 * the way to the child. */
function ReportCard({ entry }: { entry: Extract<Entry, { kind: "report" }> }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="acme-tcard" data-card="report" aria-label={`Report from ${entry.title}`}>
      <header className="acme-tcard-head">
        <ReportIcon size={16} />
        <span className="acme-tcard-kind">
          Report from <strong className="acme-tcard-who">{entry.title}</strong>
        </span>
        <Muted>{shortTime(entry.at)}</Muted>
      </header>
      <span className="acme-report-outcome" data-tone={entry.tone}>
        {entry.outcome}
      </span>
      {entry.text ? (
        <>
          <button type="button" className="acme-fold-line" aria-expanded={open} onClick={() => setOpen(!open)}>
            <ChevronRightIcon size={14} className="acme-fold-mark" />
            <span>The report</span>
          </button>
          {open ? (
            <div className="acme-tcard-body">
              <Markdown text={entry.text} />
            </div>
          ) : null}
        </>
      ) : null}
      <div className="acme-tcard-actions">
        <Link to={`/sessions/${entry.childId}`} aria-label={`Open ${entry.title}`}>
          Open
        </Link>
      </div>
    </section>
  );
}

/** What the session that started this one asked of it, linking back. */
function FromCard({ entry }: { entry: Extract<Entry, { kind: "from" }> }) {
  return (
    <section className="acme-tcard" data-card="from" aria-label={`From ${entry.title}`}>
      <header className="acme-tcard-head">
        <ParentIcon size={16} />
        <span className="acme-tcard-kind">
          From <Link to={`/sessions/${entry.sessionId}`}>{entry.title}</Link>
        </span>
        <Muted>{shortTime(entry.at)}</Muted>
      </header>
      <Markdown text={entry.text} />
    </section>
  );
}

function FoldRow({ entry }: { entry: Extract<Entry, { kind: "fold" }> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="acme-fold">
      <button type="button" className="acme-fold-line" aria-expanded={entry.text ? open : undefined} disabled={!entry.text} onClick={() => setOpen(!open)}>
        {entry.text ? <ChevronRightIcon size={14} className="acme-fold-mark" /> : null}
        <span>{entry.label}</span>
      </button>
      {open && entry.text ? (
        <div className="acme-thought-text">
          <Markdown text={entry.text} />
        </div>
      ) : null}
    </div>
  );
}

function EntryRow({ entry, vm }: { entry: Entry; vm: SessionVm }): ReactNode {
  switch (entry.kind) {
    case "person":
      return (
        <div className="acme-bubble" title={shortTime(entry.at)}>
          <Markdown text={entry.text} />
        </div>
      );
    case "note":
      return (
        <section className="acme-tcard" data-card="note" aria-label={entry.label}>
          <Muted>
            {entry.label} · {shortTime(entry.at)}
          </Muted>
          <Markdown text={entry.text} />
        </section>
      );
    case "thought":
      return <ThoughtRow entry={entry} />;
    case "prose":
      return (
        <div className="acme-prose" data-live={entry.live || undefined}>
          <Markdown text={entry.text} />
          {entry.live ? <span className="acme-caret" aria-hidden="true" /> : null}
          {entry.live ? null : (
            <div className="acme-prose-tools">
              <Muted>{shortTime(entry.at)}</Muted>
              <IconButton label="Copy" onClick={() => vm.copy(entry.text, "The text")}>
                <CopyIcon size={14} />
              </IconButton>
            </div>
          )}
        </div>
      );
    case "work":
      return <WorkBlock entry={entry} onOpen={vm.openCall} />;
    case "action":
      return <ActionCard entry={entry} vm={vm} />;
    case "ask":
      return <AskCard entry={entry} vm={vm} />;
    case "card":
      return <DeliveryCard entry={entry} />;
    case "subagents":
      return <SubAgentsCard entry={entry} />;
    case "report":
      return <ReportCard entry={entry} />;
    case "from":
      return <FromCard entry={entry} />;
    case "product": {
      const card = vm.tools[entry.line.call.tool]?.card;
      return card && vm.slotSession ? card(vm.slotSession, entry.line.call) : <CallRow line={entry.line} onOpen={vm.openCall} />;
    }
    case "line":
      return (
        <div className="acme-thin" data-tone={entry.tone}>
          <span>{entry.text}</span>
          <Muted>{shortTime(entry.at)}</Muted>
        </div>
      );
    case "fold":
      return <FoldRow entry={entry} />;
  }
}

/** Near enough to the end that new rows keep it in view. */
const NEAR_END_PX = 80;

/** The ticks on the timeline's edge, each where its row sits in the whole
 * history. Hovering, or its button, lists them; a click scrolls there. */
function Outline({ marks, scroller, onEnd }: { marks: readonly OutlineMark[]; scroller: RefObject<HTMLDivElement | null>; onEnd: () => void }) {
  const [open, setOpen] = useState(false);
  const [places, setPlaces] = useState<ReadonlyMap<string, number>>(new Map());
  const rowOf = (key: string) => scroller.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`) ?? null;
  // Each tick sits where its row does, read again whenever the history's
  // height changes.
  useLayoutEffect(() => {
    const box = scroller.current;
    const list = box?.firstElementChild;
    // Where no observer is (a page drawn outside a browser), no tick is placed.
    if (!box || !list || marks.length === 0 || typeof ResizeObserver !== "function") return;
    const place = () => {
      const height = Math.max(1, box.scrollHeight);
      const rowAt = (key: string) => box.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`)?.offsetTop ?? 0;
      setPlaces(new Map(marks.map((mark) => [mark.key, Math.min(1, rowAt(mark.key) / height)])));
    };
    const watch = new ResizeObserver(place);
    watch.observe(list);
    return () => watch.disconnect();
  }, [marks, scroller]);
  if (marks.length === 0) return null;
  const go = (key: string) => {
    rowOf(key)?.scrollIntoView({ block: "center" });
    setOpen(false);
  };
  return (
    <nav className="acme-outline" aria-label="Outline" data-open={open || undefined} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className="acme-outline-toggle" aria-expanded={open} aria-label="Outline" title="Outline" onClick={() => setOpen(!open)}>
        <OutlineIcon size={14} />
      </button>
      <div className="acme-outline-rail" aria-hidden="true">
        {marks.map((mark) => (
          <span key={mark.key} className="acme-outline-tick" data-kind={mark.kind} style={{ top: `${(places.get(mark.key) ?? 0) * 100}%` }} />
        ))}
      </div>
      {open ? (
        <ul className="acme-outline-list">
          {marks.map((mark) => (
            <li key={mark.key}>
              <button type="button" data-kind={mark.kind} onClick={() => go(mark.key)}>
                <span className="acme-outline-dot" data-kind={mark.kind} aria-hidden="true" />
                <span className="acme-outline-label">{mark.label}</span>
                <Muted>{shortTime(mark.at)}</Muted>
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              className="acme-outline-end"
              onClick={() => {
                onEnd();
                setOpen(false);
              }}
            >
              <JumpIcon size={14} />
              <span>Jump to latest</span>
            </button>
          </li>
        </ul>
      ) : null}
    </nav>
  );
}

/** The chat, scrolled to its end while the reader is there; a reader who
 * scrolled up keeps their place, and a button takes them to the latest. */
export function Timeline({ vm }: { vm: SessionVm }) {
  const chat = vm.chat;
  const scroller = useRef<HTMLDivElement>(null);
  const [atEnd, setAtEnd] = useState(true);
  const toEnd = () => {
    const box = scroller.current;
    if (box) box.scrollTop = box.scrollHeight;
  };
  useLayoutEffect(() => {
    if (atEnd) toEnd();
  }, [chat, atEnd]);
  const onScroll = () => {
    const box = scroller.current;
    if (box) setAtEnd(box.scrollHeight - box.scrollTop - box.clientHeight < NEAR_END_PX);
  };
  const status = chat?.status;
  return (
    <div className="acme-chat-frame">
      <div className="acme-chat-scroll" ref={scroller} onScroll={onScroll}>
        <ol className="acme-chat" aria-label="Timeline">
          {chat === null ? (
            <li>
              <Muted>{vm.stepsError ? "The history could not be read." : "Loading"}</Muted>
            </li>
          ) : null}
          {chat?.entries.length === 0 ? (
            <li>
              <Muted>Nothing yet. A message wakes the session.</Muted>
            </li>
          ) : null}
          {chat?.entries.map((entry) => (
            <li key={entry.key} className="acme-chat-row" data-kind={entry.kind} data-key={entry.key}>
              <EntryRow entry={entry} vm={vm} />
            </li>
          ))}
          {status ? (
            <li className="acme-chat-status" data-needs-you={status.needsYou || undefined} role="status">
              {status.working ? <SpinnerIcon size={14} className="acme-spin" /> : null}
              <span>
                <Gist text={status.text} />
              </span>
              {status.open ? (
                <Link className="acme-chat-status-open" to={`/sessions/${status.open}`}>
                  Open
                </Link>
              ) : null}
            </li>
          ) : null}
        </ol>
        {atEnd ? null : (
          <button type="button" className="acme-jump" onClick={toEnd}>
            <JumpIcon size={14} />
            <span>Jump to latest</span>
          </button>
        )}
      </div>
      <Outline marks={vm.marks} scroller={scroller} onEnd={toEnd} />
    </div>
  );
}
