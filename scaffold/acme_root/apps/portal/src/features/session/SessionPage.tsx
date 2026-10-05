// One session: its header, its history as a chat with the composer pinned
// under it, and a panel of its other parts beside them. A session the
// member's org does not hold shows nothing of it.
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { usePageCommands } from "../../app/shell/shellContext";
import {
  ArchiveIcon,
  Banner,
  Card,
  CloseIcon,
  CopyIcon,
  IconButton,
  InfoTip,
  Menu,
  MenuItem,
  MoreIcon,
  Muted,
  Page,
  PanelIcon,
  PauseIcon,
  PlayIcon,
  PullRequestIcon,
  SegmentedControl,
  SendIcon,
  TextArea,
  Tooltip,
} from "../../design/kit";
import { shortTime } from "../sessions/sessionsModel";
import { SESSION_TABS } from "./sessionModel";
import { ChangesPart, ChildrenPart, EvidencePart, LivePart, ToolCallsPart } from "./SessionParts";
import { Timeline } from "./Timeline";
import { useSessionVm, type SessionVm } from "./useSessionVm";

const back = <Link to="/sessions">← Sessions</Link>;

export function SessionPage() {
  const { sessionId = "" } = useParams();
  const vm = useSessionVm(sessionId);
  // What the page can do now, offered first in the shell's search (Cmd-K).
  usePageCommands(vm.commands);
  const { panel, setPanel } = vm;
  const running = vm.session?.raw.status === "running";
  // Option-Cmd-B shows or hides the panel.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.code !== "KeyB" || !event.altKey || !(event.metaKey || event.ctrlKey)) return;
      event.preventDefault();
      setPanel(panel === null ? (running ? "live" : "changes") : null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel, setPanel, running]);
  if (vm.missing) {
    return (
      <Page title="No session here" back={back}>
        <Card>
          <Muted>This org holds no session with this address. It may belong to another org, or it was deleted.</Muted>
        </Card>
      </Page>
    );
  }
  if (!vm.session) {
    return (
      <Page title="Session" back={back}>
        {vm.error ? <Banner>{errorMessage(vm.error, "The session could not be read.")}</Banner> : <Muted>Loading</Muted>}
      </Page>
    );
  }
  return (
    <div className="acme-app">
      <div className="acme-session" data-panel={vm.panel ? "open" : undefined}>
        <section className="acme-session-middle" aria-label="Session">
          <SessionHeader vm={vm} />
          <Timeline key={vm.id} vm={vm} />
          <Composer key={`composer-${vm.id}`} vm={vm} />
        </section>
        {vm.panel ? <SessionPanel vm={vm} /> : null}
      </div>
    </div>
  );
}

/** The status (its tip says why it waits and what clears it), the title, the
 * pull request it opened, its details, Pause or Resume, the rest in a menu,
 * and the panel's toggle. */
function SessionHeader({ vm }: { vm: SessionVm }) {
  const session = vm.session!;
  const raw = session.raw;
  const may = vm.may;
  const park = vm.park;
  const why = park
    ? `${park.reason} It is cleared by ${park.unlock}.${park.retryAt ? ` It tries again by itself at ${shortTime(park.retryAt)}.` : ""}`
    : `It is ${session.status.label}.`;
  const opens = raw.status === "running" ? "live" : "changes";
  return (
    <header className="acme-session-head">
      <Tooltip tip={why}>
        <button type="button" className="acme-pill acme-status-pill" data-tone={session.status.tone}>
          {session.status.label}
        </button>
      </Tooltip>
      <h1 className="acme-session-title">{session.title}</h1>
      {vm.pullRequest ? (
        <span className="acme-pr-badge" title={vm.pullRequest.handle}>
          <PullRequestIcon size={14} />
          {vm.pullRequest.label}
          {vm.pullRequest.more > 0 ? ` +${vm.pullRequest.more}` : ""}
        </span>
      ) : null}
      <InfoTip label="Details" side="bottom">
        {raw.kind} v{raw.kind_version} · started {shortTime(raw.created_at)}
        {raw.parent_id ? " · a sub-agent" : ""}
      </InfoTip>
      {raw.parent_id ? (
        <Link className="acme-head-link" to={`/sessions/${raw.parent_id}`}>
          Its parent
        </Link>
      ) : null}
      <span className="acme-composer-gap" />
      {park?.action === "give_back" && may?.giveBack ? (
        <button type="button" className="acme-chip" onClick={() => vm.setPanel("live")}>
          <span>Give it back</span>
        </button>
      ) : null}
      {may?.pause ? (
        <Tooltip tip="Pause after the current step">
          <button type="button" className="acme-chip" onClick={() => vm.control("pause")}>
            <PauseIcon size={14} />
            <span>Pause</span>
          </button>
        </Tooltip>
      ) : null}
      {may?.resume ? (
        <button type="button" className="acme-chip" onClick={() => vm.control("resume")}>
          <PlayIcon size={14} />
          <span>Resume</span>
        </button>
      ) : null}
      <Menu label="More" trigger={<MoreIcon />} triggerLabel="More" triggerClassName="acme-icon-button" align="end">
        {may?.compact ? <MenuItem onSelect={() => vm.control("compact")}>Compact history</MenuItem> : null}
        {may?.cancel ? (
          <MenuItem tone="danger" onSelect={() => vm.control("cancel")}>
            End this run
          </MenuItem>
        ) : null}
        {may?.archive ? (
          <MenuItem icon={<ArchiveIcon />} onSelect={vm.archive}>
            Archive
          </MenuItem>
        ) : null}
        <MenuItem icon={<CopyIcon />} onSelect={vm.copyLink}>
          Copy link
        </MenuItem>
      </Menu>
      <Tooltip tip={vm.panel ? "Hide the panel" : "Show the panel"} shortcut="⌥⌘B">
        <button
          type="button"
          className="acme-icon-button"
          aria-label={vm.panel ? "Hide the panel" : "Show the panel"}
          aria-pressed={vm.panel !== null}
          onClick={() => vm.setPanel(vm.panel ? null : opens)}
        >
          <PanelIcon />
        </button>
      </Tooltip>
    </header>
  );
}

/** Pinned under the chat: a reply or a steer, or the answer while the agent
 * asks; Send on Cmd-Enter; Pause while it runs. */
function Composer({ vm }: { vm: SessionVm }) {
  const [draft, setDraft] = useState("");
  if (!vm.may?.send) {
    return (
      <div className="acme-session-composer">
        <Muted>A member who may write sends messages here.</Muted>
      </div>
    );
  }
  const submit = () => {
    if (draft.trim() && !vm.sending) vm.send(draft.trim(), () => setDraft(""));
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey)) return;
    event.preventDefault();
    submit();
  };
  return (
    <div className="acme-session-composer">
      <form className="acme-composer" aria-label="Send a message" onSubmit={onSubmit}>
        <TextArea label={vm.composer.label} hideLabel rows={2} placeholder={vm.composer.placeholder} value={draft} onChange={setDraft} onKeyDown={onKey} />
        <div className="acme-composer-bar">
          <span className="acme-composer-gap" />
          {vm.may.pause ? (
            <Tooltip tip="Pause after the current step" side="top">
              <button type="button" className="acme-chip" onClick={() => vm.control("pause")}>
                <PauseIcon size={14} />
                <span>Pause</span>
              </button>
            </Tooltip>
          ) : null}
          <Tooltip tip="Send" shortcut="⌘↵" side="top">
            <button type="submit" className="acme-send" aria-label="Send" disabled={vm.sending || !draft.trim()}>
              <SendIcon />
            </button>
          </Tooltip>
        </div>
      </form>
    </div>
  );
}

/** The session's other parts, one at a time, beside the chat. */
function SessionPanel({ vm }: { vm: SessionVm }) {
  if (vm.panel === null) return null;
  return (
    <aside className="acme-session-panel" aria-label="Session panel">
      <div className="acme-session-panel-head">
        <SegmentedControl label="Part of the session" value={vm.panel} options={SESSION_TABS} onChange={vm.setPanel} />
        <IconButton label="Hide the panel" onClick={() => vm.setPanel(null)}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="acme-session-panel-body">
        {vm.panel === "tools" ? <ToolCallsPart vm={vm} /> : null}
        {vm.panel === "evidence" ? <EvidencePart vm={vm} /> : null}
        {vm.panel === "changes" ? <ChangesPart vm={vm} /> : null}
        {vm.panel === "children" ? <ChildrenPart vm={vm} /> : null}
        {vm.panel === "live" ? <LivePart vm={vm} /> : null}
      </div>
    </aside>
  );
}
