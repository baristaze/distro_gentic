import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, type AgentSessionView } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import type { SlotSession } from "../../app/product";
import { useShellSessions } from "../../app/shell/shellContext";
import { waitingBeneath } from "../../app/shell/shellModel";
import { useSlot } from "../../app/slot";
import type { PaletteCommand } from "../../design/kit";
import { useAgentSession, useApprovals, useChildren, useChildSteps, useCommandProgress, useDelivery, useSessionActions, useSessionRecords, useSteps } from "../../queries/agentSessions";
import { useLiveStreams } from "../../queries/live";
import { useMe } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { paneOf, usePanesStore } from "../../store/panes";
import { sessionRow } from "../sessions/sessionsModel";
import { addable, closeTab, knownTabs, openCall, openTab, openThemselves, resizePane, shownTab, togglePane, type PaneState } from "./paneModel";
import { allowed, composerOf, deliveryLines, parkLine, pullRequestBadge, splitCommand, statusLine } from "./sessionModel";
import { answers, callsOf, handedTo, outline, timeline, type Call, type ChildState } from "./timelineModel";

const NONE: readonly AgentSessionView[] = [];

/** A session it started as its page reads it, before what it does now is read. */
const stateOf = (other: AgentSessionView): ChildState => ({
  id: other.id,
  title: other.title,
  kind: other.kind,
  status: other.status,
  park: other.park,
  archived_at: other.archived_at,
  created_at: other.created_at,
  activity: null,
  waits: null,
});

/** The time now, read again every second while `ticking`: a running block's
 * duration counts up. */
export function useNow(ticking: boolean): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);
  return now;
}

/** A product's predicate, read safely: one that throws says no. */
function asks(predicate: ((s: SlotSession) => boolean) | undefined, s: SlotSession): boolean {
  try {
    return predicate?.(s) === true;
  } catch {
    return false;
  }
}

/** One session's page: its header, its history as a chat with what streams
 * now at its end, the composer under it, and its right pane of tabs. Its
 * reads wait on the session itself: a session the member's org does not
 * hold answers 404, and then nothing else is asked for. A tab reads its own
 * routes, and only while it is drawn. */
export function useSessionVm(id: string) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const notify = useNoticesStore((s) => s.notify);
  const slot = useSlot();
  const me = useMe();
  const session = useAgentSession(id);
  const found = session.isSuccess;
  const status = session.data?.status;
  const active = status === "running" || status === "pending" || status === "parked";
  const steps = useSteps(id, active, found);
  const approvals = useApprovals(id, found && status === "parked");
  const delivery = useDelivery(id, found);
  // A session reads as pending until a step after its input is projected,
  // which can be its run's park: its first run streams while it is pending.
  const runs = status === "running" || status === "pending";
  const live = useLiveStreams(id, found && runs);
  // Its sub-agents, what each works on now, and the session that started it.
  const childList = useChildren(id, found);
  const childRecords = childList.data ?? NONE;
  const childSteps = useChildSteps(childRecords);
  // What waits on a person beneath each child, from the sessions the shell
  // keeps live: a sub-agent's sub-agent is no child of this one.
  const listed = useShellSessions();
  const waits = useMemo(() => waitingBeneath(listed, childRecords), [listed, childRecords]);
  const parentId = session.data?.parent_id ?? null;
  const parentRead = useAgentSession(parentId ?? "", parentId !== null);
  // The sessions its hand-offs started, each read as its own page reads it:
  // none is a child of it. A read that answers for another id is no record.
  const handedIds = useMemo(() => handedTo(steps.data ?? []), [steps.data]);
  const handedRead = useSessionRecords(handedIds);
  const handedRecords = useMemo(
    () => handedRead.flatMap((other, index) => (other && other.id === handedIds[index] ? [other] : [])),
    [handedRead, handedIds],
  );
  // The clock ticks while it runs, or while a session it started does: their rows time them.
  const works = (other: AgentSessionView) => other.archived_at === null && other.status !== "idle";
  const now = useNow(runs || childRecords.some(works) || handedRecords.some(works));
  const actions = useSessionActions(id);
  const [commandKey, setCommandKey] = useState<string | null>(null);
  const command = useCommandProgress(id, commandKey);
  const [commandProblem, setCommandProblem] = useState<string | null>(null);

  // A stream that ends has become a step: read it now, not at the next poll,
  // so its words stay on screen.
  const streaming = useRef<ReadonlySet<string>>(new Set());
  const refetchSteps = steps.refetch;
  useEffect(() => {
    const open = new Set(live.map((stream) => stream.stepId));
    const ended = [...streaming.current].some((stepId) => !open.has(stepId));
    streaming.current = open;
    if (ended) void refetchSteps();
  }, [live, refetchSteps]);

  const may = session.data ? allowed(session.data, me.data?.permissions.includes("write") ?? false) : null;
  const fail = useCallback((what: string) => (caught: unknown) => notify(errorMessage(caught, what), { tone: "problem" }), [notify]);

  // The pane: kept per session in this browser, its active tab and the call
  // Step shows mirrored in the address (`?pane=`, `?call=`).
  const tabs = slot.sessionTabs;
  const known = useMemo(() => new Set(tabs.map((tab) => tab.id)), [tabs]);
  const kept = usePanesStore((s) => paneOf(s.panes, id));
  const changePane = usePanesStore((s) => s.change);
  const pane = useMemo(() => knownTabs(kept, known), [kept, known]);
  const change = useCallback((next: (pane: PaneState) => PaneState) => changePane(id, (before) => next(knownTabs(before, known))), [changePane, id, known]);
  const shown = shownTab(pane);
  const stepCall = pane.step;
  // Each time a person asks to see a tab or a step (a call line, a command,
  // the address), past the tabs that open themselves: a pane folded to its
  // rail shows what was asked. They count afresh for each session, from the
  // address the visit opens at.
  const addressAsks = (): number => {
    const tab = params.get("pane");
    return tab !== null && known.has(tab) ? 1 : 0;
  };
  const [asked, setAsked] = useState(() => ({ id, count: addressAsks() }));
  if (asked.id !== id) setAsked({ id, count: addressAsks() });
  const ask = useCallback(
    (next: (pane: PaneState) => PaneState) => {
      change(next);
      setAsked((before) => ({ id, count: (before.id === id ? before.count : 0) + 1 }));
    },
    [change, id],
  );
  // The address the page opens at names a tab, and a call: they open, once a visit.
  const visited = useRef<string | null>(null);
  useEffect(() => {
    if (visited.current === id) return;
    visited.current = id;
    const asked = params.get("pane");
    const call = params.get("call");
    if (asked !== null && known.has(asked)) change((before) => (call ? openCall(before, asked, call) : openTab(before, asked)));
  }, [id, known, change, params]);
  // Then the address follows the pane: the pane is its one writer.
  useEffect(() => {
    const now = knownTabs(paneOf(usePanesStore.getState().panes, id), known);
    const tab = shownTab(now);
    const call = tab === null ? null : now.step;
    if (params.get("pane") === tab && params.get("call") === call) return;
    const next = new URLSearchParams(params);
    for (const [key, value] of [
      ["pane", tab],
      ["call", call],
    ] as const) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace: true });
  }, [shown, stepCall, params, setParams, id, known]);
  const showTab = useCallback((tab: string) => ask((before) => openTab(before, tab)), [ask]);

  const send = (text: string, done: () => void) =>
    actions.message.mutate(text, { onSuccess: done, onError: fail("The message was not sent.") });
  const control = (command: "pause" | "resume" | "cancel" | "compact" | "unlock") =>
    actions.control.mutate({ command }, { onError: fail(`The ${command} was not sent.`) });
  const decide = (seq: number, approve: boolean, note: string) =>
    actions.decide.mutate({ seq, approve, ...(note.trim() ? { note: note.trim() } : {}) }, { onError: fail("The decision was not sent.") });
  const takeControl = () => actions.takeControl.mutate(undefined, { onError: fail("Control was not taken.") });
  /** A line the shell would read otherwise is never sent: its reason shows instead. */
  const runCommand = (line: string, done: () => void) => {
    const split = splitCommand(line);
    if ("problem" in split) {
      setCommandProblem(split.problem);
      return;
    }
    setCommandProblem(null);
    actions.runCommand.mutate(
      { argv: split.argv },
      {
        onSuccess: (run) => {
          setCommandKey(run.command_key);
          done();
        },
        onError: fail("The command did not run."),
      },
    );
  };
  const giveBack = (summary: string) =>
    actions.giveBack.mutate({ summary: summary.trim() }, { onSuccess: () => setCommandKey(null), onError: fail("Control was not given back.") });
  const archive = () =>
    actions.archive.mutate(undefined, {
      onSuccess: () => notify("The session is archived. A message brings it back."),
      onError: fail("The session was not archived."),
    });
  /** Puts `text` on the clipboard and says so; `what` names it: "The link". */
  const copy = (text: string, what: string) => {
    void (navigator.clipboard?.writeText(text) ?? Promise.reject(new Error("no clipboard"))).then(
      () => notify(`${what} is copied.`),
      fail(`${what} was not copied.`),
    );
  };
  const copyLink = () => copy(window.location.href.split("?")[0]!, "The link");

  const commands: PaletteCommand[] = useMemo(() => {
    const list: PaletteCommand[] = tabs.map((each) => ({
      id: `tab-${each.id}`,
      label: `Show ${each.label.toLowerCase()}`,
      keywords: ["tab", "panel"],
      run: () => showTab(each.id),
    }));
    list.push({ id: "sessions", label: "Go to sessions", keywords: ["list", "back"], run: () => navigate("/sessions") });
    if (may?.pause) list.push({ id: "pause", label: "Pause the session", run: () => control("pause") });
    if (may?.resume) list.push({ id: "resume", label: "Resume the session", run: () => control("resume") });
    if (may?.cancel) list.push({ id: "cancel", label: "End this run", keywords: ["stop", "cancel"], run: () => control("cancel") });
    if (may?.compact) list.push({ id: "compact", label: "Compact the history", run: () => control("compact") });
    if (may?.takeControl) list.push({ id: "take", label: "Take control", keywords: ["terminal", "hands"], run: takeControl });
    if (may?.archive) list.push({ id: "archive", label: "Archive the session", run: archive });
    return list;
    // The actions' closures are rebuilt each render; the list follows what may be done.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [may?.pause, may?.resume, may?.cancel, may?.compact, may?.takeControl, may?.archive, tabs, showTab, navigate]);

  const missing = session.error instanceof ApiError && session.error.status === 404;
  const tools = slot.tools;
  const gists = useMemo(() => Object.fromEntries(Object.entries(tools).map(([name, tool]) => [name, tool.gist])), [tools]);
  const carded = useMemo(() => new Set(Object.entries(tools).flatMap(([name, tool]) => (tool.card ? [name] : []))), [tools]);
  const held = approvals.data;
  const record = session.data;
  const history = steps.data;
  const children = useMemo<ChildState[]>(
    () =>
      childRecords.map((child, index) => {
        const read = childSteps[index];
        const own = read ? timeline({ steps: read, live: [], session: child, held: [], gists, carded, children: [], handed: [], parent: null, now }).status.text : null;
        return { ...stateOf(child), activity: own, waits: waits.get(child.id) ?? null };
      }),
    [childRecords, childSteps, waits, gists, carded, now],
  );
  const handed = useMemo<ChildState[]>(() => handedRecords.map(stateOf), [handedRecords]);
  const parentData = parentRead.data;
  const parent = useMemo(() => (parentData ? { id: parentData.id, title: parentData.title } : null), [parentData]);
  const chat = useMemo(
    () => (record && history ? timeline({ steps: history, live, session: record, held: held ?? [], gists, carded, children, handed, parent, now }) : null),
    [record, history, live, held, gists, carded, children, handed, parent, now],
  );
  const marks = useMemo(() => (chat ? outline(chat.entries) : []), [chat]);
  const slotSession: SlotSession | null = useMemo(
    () =>
      record
        ? {
            session: record,
            calls: chat ? callsOf(chat.entries) : [],
            // A session reads pending through its first run until it parks.
            running: record.status === "running" || record.status === "pending",
            open: showTab,
          }
        : null,
    [record, chat, showTab],
  );
  const offers = useMemo(
    () =>
      slotSession && chat
        ? tabs.map((tab) => ({ tab, offered: asks(tab.offered, slotSession), opensItself: asks(tab.opensItself, slotSession) }))
        : [],
    [tabs, slotSession, chat],
  );
  // A tab that first has something opens itself, once a session.
  const wanting = offers.filter((offer) => offer.offered && offer.opensItself).map((offer) => offer.tab.id).join(" ");
  useEffect(() => {
    if (wanting) change((before) => openThemselves(before, wanting.split(" ")));
  }, [wanting, change]);
  /** Shows a call: in the tab its tool names, else in Step. */
  const showCall = useCallback(
    (call: Pick<Call, "id" | "tool">) => {
      const tab = tools[call.tool]?.tab;
      const target = tab !== undefined && known.has(tab) ? tab : "step";
      ask((before) => openCall(before, target, call.id));
    },
    [tools, known, ask],
  );
  const byId = (tabId: string) => tabs.find((tab) => tab.id === tabId);
  const openIds = new Set(pane.tabs);
  const asking = chat?.entries.some(answers) ?? false;
  return {
    id,
    tabs,
    pane: {
      width: pane.width,
      shown,
      open: pane.tabs.flatMap((tabId) => byId(tabId) ?? []),
      addable: addable(pane, offers.map((offer) => ({ id: offer.tab.id, offered: offer.offered, opensItself: offer.opensItself }))).flatMap(
        (tabId) => byId(tabId) ?? [],
      ),
      isOpen: (tabId: string) => openIds.has(tabId),
      /** How many times a person has asked to see a tab or a step. */
      asks: asked.id === id ? asked.count : 0,
    },
    openTab: showTab,
    closeTab: (tabId: string) => change((before) => closeTab(before, tabId)),
    /** Hides the pane, or shows it: at Workspace while it runs, else at Changes, when no tab is open. */
    togglePane: () => change((before) => togglePane(before, slotSession?.running ? "workspace" : "changes")),
    resizePane: (width: number) => change((before) => resizePane(before, width)),
    stepCall,
    openCall: showCall,
    /** Shows the call with this id in Step. */
    openStep: (callId: string) => showCall({ id: callId, tool: "" }),
    gists,
    missing,
    error: missing ? null : session.error,
    session: record ? { ...sessionRow(record), raw: record, status: statusLine(record) } : null,
    park: record?.park ? parkLine(record.park) : null,
    may,
    chat,
    marks,
    /** Its sub-agents, each with what it does now. */
    children,
    childrenPending: childList.isPending,
    stepsError: steps.error,
    slotSession,
    tools,
    composer: composerOf(asking, slot.examples.reply),
    pullRequest: delivery.data ? pullRequestBadge(delivery.data) : null,
    delivery: delivery.data ? deliveryLines(delivery.data) : null,
    live,
    command: command.data ?? null,
    commandKey,
    send,
    control,
    decide,
    takeControl,
    runCommand,
    commandProblem,
    giveBack,
    copy,
    copyLink,
    archive,
    sending: actions.message.isPending,
    deciding: actions.decide.isPending,
    commands,
  };
}

export type SessionVm = ReturnType<typeof useSessionVm>;
