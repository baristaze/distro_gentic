// A session's history as a chat: each entry the timeline model makes, drawn
// as its row, and the status line under the last. Nothing here reads or
// decides: a row folds or opens, and a card's button calls the view-model.
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
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
  PlanIcon,
  PullRequestIcon,
  ResultIcon,
  SpinnerIcon,
  SubAgentIcon,
  TextField,
  ValidationIcon,
  parseJsonText,
  type KitIcon,
} from "../../design/kit";
import { shortTime } from "../sessions/sessionsModel";
import { CUT_NOTE, duration, type BodyKind, type CallLine, type CallState, type CardKind, type Entry, type ThoughtEntry } from "./timelineModel";
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

function Body({ kind, text, label }: { kind: BodyKind; text: string; label: string }): ReactNode {
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

function StateMark({ state }: { state: CallState }) {
  const Icon = state === "done" ? CheckIcon : state === "held" ? HeldIcon : state === "failed" || state === "denied" ? FailedIcon : state === "stopped" ? FailedIcon : SpinnerIcon;
  return (
    <span className="acme-call-state" data-state={state} role="img" aria-label={STATE_WORDS[state]} title={STATE_WORDS[state]}>
      <Icon size={14} />
    </span>
  );
}

/** One call: its state, its line, and the chevron that shows its answer
 * inline. A running call shows what it streams without a click. */
function CallRow({ line }: { line: CallLine }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const has = line.bodyKind !== "none";
  const shown = has && (open ?? (line.call.output === null && line.call.liveOutput !== null));
  return (
    <div className="acme-call" data-tool={line.call.tool} data-state={line.call.state}>
      <button type="button" className="acme-call-line" aria-expanded={has ? shown : undefined} disabled={!has} onClick={() => setOpen(!shown)}>
        <StateMark state={line.call.state} />
        <span className="acme-call-gist">
          <Gist text={line.gist} />
        </span>
        {has ? <ChevronRightIcon size={14} className="acme-fold-mark" /> : null}
      </button>
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

function WorkBlock({ entry }: { entry: Extract<Entry, { kind: "work" }> }) {
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
          {entry.items.map((item) => (item.kind === "call" ? <CallRow key={item.key} line={item} /> : <ThoughtRow key={item.key} entry={item} />))}
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
      <CallRow line={entry.line} />
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

function SubAgentCard({ entry }: { entry: Extract<Entry, { kind: "subagent" }> }) {
  return (
    <section className="acme-tcard" data-card="subagent" aria-label="Sub-agent">
      <header className="acme-tcard-head">
        <SubAgentIcon size={16} />
        <span className="acme-tcard-kind">Sub-agent · {entry.agent}</span>
        <StateMark state={entry.line.call.state} />
      </header>
      <strong className="acme-tcard-title">{entry.title}</strong>
      {entry.childId ? (
        <div className="acme-tcard-actions">
          <Link to={`/sessions/${entry.childId}`}>Open</Link>
        </div>
      ) : null}
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
      return <WorkBlock entry={entry} />;
    case "action":
      return <ActionCard entry={entry} vm={vm} />;
    case "ask":
      return <AskCard entry={entry} vm={vm} />;
    case "card":
      return <DeliveryCard entry={entry} />;
    case "subagent":
      return <SubAgentCard entry={entry} />;
    case "product": {
      const card = vm.tools[entry.line.call.tool]?.card;
      return card && vm.slotSession ? card(vm.slotSession, entry.line.call) : <CallRow line={entry.line} />;
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
  return (
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
          <li key={entry.key} className="acme-chat-row" data-kind={entry.kind}>
            <EntryRow entry={entry} vm={vm} />
          </li>
        ))}
        {chat ? (
          <li className="acme-chat-status" data-needs-you={chat.status.needsYou || undefined} role="status">
            {chat.status.working ? <SpinnerIcon size={14} className="acme-spin" /> : null}
            <span>{chat.status.text}</span>
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
  );
}
