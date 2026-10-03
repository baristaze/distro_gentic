import { useCallback, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import type { PaletteCommand } from "../../design/kit";
import {
  useAgentSession,
  useApprovals,
  useBounds,
  useChildren,
  useCommandProgress,
  useDelivery,
  useExecutions,
  useQuestions,
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
  asks,
  deliveryLines,
  parkLine,
  runRow,
  SESSION_TABS,
  sessionTab,
  splitCommand,
  statusLine,
  thread,
  timeline,
  toolCallRow,
  usageLine,
  type SessionTab,
} from "./sessionModel";

/** One session's page. Its reads wait on the session itself: a session the
 * member's org does not hold answers 404, and then nothing else is asked
 * for. Each part of the page reads only when it is open, and a part that
 * changes while the session runs is read again every few seconds. */
export function useSessionVm(id: string) {
  const [params, setParams] = useSearchParams();
  const tab = sessionTab(params.get("tab"));
  const navigate = useNavigate();
  const notify = useNoticesStore((s) => s.notify);
  const me = useMe();
  const session = useAgentSession(id);
  const found = session.isSuccess;
  const status = session.data?.status;
  const active = status === "running" || status === "pending" || status === "parked";
  const steps = useSteps(id, active, found && (tab === "thread" || tab === "timeline"));
  const toolCalls = useToolCalls(id, active, found && tab === "tools");
  const approvals = useApprovals(id, found && status === "parked");
  const questions = useQuestions(id, found && status === "parked");
  const executions = useExecutions(id, found && tab === "evidence");
  const validations = useValidations(id, found && tab === "evidence");
  const usage = useUsage(id, found && tab === "evidence");
  const bounds = useBounds(id, found && (tab === "evidence" || tab === "children"));
  const delivery = useDelivery(id, found && tab === "changes");
  const children = useChildren(id, found && tab === "children");
  const live = useLiveStreams(id, found && tab === "live" && status === "running");
  const actions = useSessionActions(id);
  const [commandKey, setCommandKey] = useState<string | null>(null);
  const command = useCommandProgress(id, commandKey);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shown, setShown] = useState<number | null>(null);
  const [commandProblem, setCommandProblem] = useState<string | null>(null);

  const may = session.data ? allowed(session.data, me.data?.permissions.includes("write") ?? false) : null;
  const fail = useCallback((what: string) => (caught: unknown) => notify(errorMessage(caught, what), { tone: "problem" }), [notify]);
  const setTab = useCallback(
    (next: SessionTab) => setParams(next === "thread" ? {} : { tab: next }, { replace: true }),
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

  const commands: PaletteCommand[] = useMemo(() => {
    const list: PaletteCommand[] = SESSION_TABS.map((each) => ({
      id: `tab-${each.value}`,
      label: `Show ${each.label.toLowerCase()}`,
      run: () => setTab(each.value),
    }));
    list.push({ id: "sessions", label: "Go to sessions", keywords: ["list", "back"], run: () => navigate("/sessions") });
    if (may?.pause) list.push({ id: "pause", label: "Pause the session", run: () => control("pause") });
    if (may?.resume) list.push({ id: "resume", label: "Resume the session", run: () => control("resume") });
    if (may?.cancel) list.push({ id: "cancel", label: "Cancel the loop", keywords: ["stop"], run: () => control("cancel") });
    if (may?.compact) list.push({ id: "compact", label: "Compact the history", run: () => control("compact") });
    if (may?.takeControl) list.push({ id: "take", label: "Take control", keywords: ["terminal", "hands"], run: takeControl });
    if (may?.archive) list.push({ id: "archive", label: "Archive the session", run: archive });
    return list;
    // The actions' closures are rebuilt each render; the list follows what may be done.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [may?.pause, may?.resume, may?.cancel, may?.compact, may?.takeControl, may?.archive, setTab, navigate]);

  const missing = session.error instanceof ApiError && session.error.status === 404;
  // Read again only when a step is added: the history holds its steps from one read to the next.
  const history = steps.data;
  const said = useMemo(() => (history ? thread(history) : null), [history]);
  const lines = useMemo(() => (history ? timeline(history) : null), [history]);
  return {
    id,
    tab,
    setTab,
    missing,
    error: missing ? null : session.error,
    session: session.data ? { ...sessionRow(session.data), raw: session.data, status: statusLine(session.data) } : null,
    park: session.data?.park ? parkLine(session.data.park) : null,
    asks: asks(approvals.data ?? [], questions.data ?? []),
    may,
    thread: steps.isPending ? null : (said ?? []),
    timeline: steps.isPending ? null : (lines ?? []),
    stepsError: steps.error,
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
    sending: actions.message.isPending,
    commands,
    paletteOpen,
    setPaletteOpen,
    shown,
    setShown,
  };
}

export type SessionVm = ReturnType<typeof useSessionVm>;
