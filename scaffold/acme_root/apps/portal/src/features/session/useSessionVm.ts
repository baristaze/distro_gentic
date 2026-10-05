import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import type { SlotSession } from "../../app/product";
import { useSlot } from "../../app/slot";
import type { PaletteCommand } from "../../design/kit";
import {
  useAgentSession,
  useApprovals,
  useBounds,
  useChildren,
  useCommandProgress,
  useDelivery,
  useExecutions,
  useSessionActions,
  useSteps,
  useToolCalls,
  useUsage,
  useValidations,
} from "../../queries/agentSessions";
import { useLiveStreams } from "../../queries/live";
import { useMe } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { sessionRow } from "../sessions/sessionsModel";
import {
  allowed,
  composerOf,
  deliveryLines,
  parkLine,
  pullRequestBadge,
  runRow,
  SESSION_TABS,
  sessionPanel,
  splitCommand,
  statusLine,
  toolCallRow,
  usageLine,
  type SessionTab,
} from "./sessionModel";
import { answers, callsOf, timeline } from "./timelineModel";

/** The time now, read again every second while `ticking`: a running block's
 * duration counts up. */
function useNow(ticking: boolean): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, [ticking]);
  return now;
}

/** One session's page: its header, its history as a chat with what streams
 * now at its end, the composer under it, and a panel of its other parts.
 * Its reads wait on the session itself: a session the member's org does
 * not hold answers 404, and then nothing else is asked for. A part of the
 * panel reads only while it is open. */
export function useSessionVm(id: string) {
  const [params, setParams] = useSearchParams();
  const panel = sessionPanel(params.get("tab"));
  const navigate = useNavigate();
  const notify = useNoticesStore((s) => s.notify);
  const slot = useSlot();
  const me = useMe();
  const session = useAgentSession(id);
  const found = session.isSuccess;
  const status = session.data?.status;
  const active = status === "running" || status === "pending" || status === "parked";
  const steps = useSteps(id, active, found);
  const toolCalls = useToolCalls(id, active, found && panel === "tools");
  const approvals = useApprovals(id, found && status === "parked");
  const executions = useExecutions(id, found && panel === "evidence");
  const validations = useValidations(id, found && panel === "evidence");
  const usage = useUsage(id, found && panel === "evidence");
  const bounds = useBounds(id, found && (panel === "evidence" || panel === "children"));
  const delivery = useDelivery(id, found);
  const children = useChildren(id, found && panel === "children");
  const live = useLiveStreams(id, found && status === "running");
  const now = useNow(status === "running" || status === "pending");
  const actions = useSessionActions(id);
  const [commandKey, setCommandKey] = useState<string | null>(null);
  const command = useCommandProgress(id, commandKey);
  const [shown, setShown] = useState<number | null>(null);
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
  const setPanel = useCallback(
    (next: SessionTab | null) => setParams(next === null ? {} : { tab: next }, { replace: true }),
    [setParams],
  );

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
    const list: PaletteCommand[] = SESSION_TABS.map((each) => ({
      id: `tab-${each.value}`,
      label: `Show ${each.label.toLowerCase()}`,
      run: () => setPanel(each.value),
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
  }, [may?.pause, may?.resume, may?.cancel, may?.compact, may?.takeControl, may?.archive, setPanel, navigate]);

  const missing = session.error instanceof ApiError && session.error.status === 404;
  const tools = slot.tools;
  const gists = useMemo(() => Object.fromEntries(Object.entries(tools).map(([name, tool]) => [name, tool.gist])), [tools]);
  const carded = useMemo(() => new Set(Object.entries(tools).flatMap(([name, tool]) => (tool.card ? [name] : []))), [tools]);
  const held = approvals.data;
  const record = session.data;
  const history = steps.data;
  const chat = useMemo(
    () => (record && history ? timeline({ steps: history, live, session: record, held: held ?? [], gists, carded, now }) : null),
    [record, history, live, held, gists, carded, now],
  );
  const slotSession: SlotSession | null = useMemo(
    () =>
      record
        ? {
            session: record,
            calls: chat ? callsOf(chat.entries) : [],
            running: record.status === "running",
            open: (tab: string) => setPanel(sessionPanel(tab)),
          }
        : null,
    [record, chat, setPanel],
  );
  const asking = chat?.entries.some(answers) ?? false;
  return {
    id,
    panel,
    setPanel,
    missing,
    error: missing ? null : session.error,
    session: record ? { ...sessionRow(record), raw: record, status: statusLine(record) } : null,
    park: record?.park ? parkLine(record.park) : null,
    may,
    chat,
    stepsError: steps.error,
    slotSession,
    tools,
    composer: composerOf(asking, slot.examples.reply),
    pullRequest: delivery.data ? pullRequestBadge(delivery.data) : null,
    toolCalls: toolCalls.isPending ? null : (toolCalls.data ?? []).map(toolCallRow),
    runs: executions.isPending ? null : (executions.data ?? []).map(runRow),
    rawRuns: executions.data ?? [],
    validations: validations.data ?? [],
    usage: usage.data ? usageLine(usage.data) : null,
    bounds: bounds.data ?? null,
    delivery: delivery.data ? deliveryLines(delivery.data) : null,
    children: children.isPending ? null : (children.data ?? []).map(sessionRow),
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
    shown,
    setShown,
  };
}

export type SessionVm = ReturnType<typeof useSessionVm>;
