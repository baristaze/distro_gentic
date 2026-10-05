import { useCallback, useMemo } from "react";
import { useAgentSession, useApprovals, useSendMessage, useSessionActions, useStartSession, useSteps } from "../../queries/agentSessions";
import { useLiveStreams } from "../../queries/live";
import { useMe } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { useSupportStore } from "../../store/support";
import { allowed } from "../../features/session/sessionModel";
import type { TimelineVm } from "../../features/session/Timeline";
import { callsOf, outline, timeline } from "../../features/session/timelineModel";
import { useNow } from "../../features/session/useSessionVm";
import { errorMessage } from "../errorMessage";
import type { SlotSession } from "../product";
import { useSlot } from "../slot";
import { ASSISTANT_KIND, continues, conversationKey, SUPPORT_TITLE } from "./supportModel";
import { withPage, type PageContext } from "./supportLinks";

const NOTHING: readonly never[] = [];

/** The support dock's conversation: the person's standing session with the
 * platform assistant, read as its page reads it, compact. The id this
 * browser keeps is read back first, and nothing else of it is asked for
 * unless it is the person's own. A message carries the page the person is
 * on, as data, and the first one starts the conversation. Send works at any
 * time: a message sent while the assistant works is queued, and its next
 * step reads it. */
export function useSupportVm(page: PageContext) {
  const slot = useSlot();
  const me = useMe();
  const notify = useNoticesStore((s) => s.notify);
  const meId = me.data?.user.id ?? null;
  const key = conversationKey(me.data?.org.id ?? null, meId);
  const keptId = useSupportStore((s) => (key ? (s.conversations[key] ?? null) : null));
  const keep = useSupportStore((s) => s.keep);
  const forget = useSupportStore((s) => s.forget);
  const kept = useAgentSession(keptId ?? "", keptId !== null);
  const record = kept.data && kept.data.id === keptId && continues(kept.data, meId) ? kept.data : undefined;
  const id = record?.id ?? null;
  const status = record?.status;
  const runs = status === "running" || status === "pending";
  const steps = useSteps(id ?? "", runs || status === "parked", id !== null);
  const approvals = useApprovals(id ?? "", id !== null && status === "parked");
  const live = useLiveStreams(id ?? "", id !== null && runs);
  const now = useNow(runs);
  const actions = useSessionActions(id ?? "");
  const start = useStartSession();
  const message = useSendMessage();
  const fail = useCallback((what: string) => (caught: unknown) => notify(errorMessage(caught, what), { tone: "problem" }), [notify]);

  const tools = slot.tools;
  const gists = useMemo(() => Object.fromEntries(Object.entries(tools).map(([name, tool]) => [name, tool.gist])), [tools]);
  const carded = useMemo(() => new Set(Object.entries(tools).flatMap(([name, tool]) => (tool.card ? [name] : []))), [tools]);
  const history = steps.data;
  const held = approvals.data;
  const chat = useMemo(
    () =>
      record && history
        ? timeline({ steps: history, live, session: record, held: held ?? [], gists, carded, children: NOTHING, handed: NOTHING, parent: null, now })
        : null,
    [record, history, live, held, gists, carded, now],
  );
  const marks = useMemo(() => (chat ? outline(chat.entries) : []), [chat]);
  const slotSession: SlotSession | null = useMemo(
    () => (record ? { session: record, calls: chat ? callsOf(chat.entries) : [], running: runs, open: () => undefined } : null),
    [record, chat, runs],
  );
  const mayWrite = me.data?.permissions.includes("write") ?? false;
  const may = record ? allowed(record, mayWrite) : null;

  /** Sends what the person typed, with the page they are on; the first
   * message starts the conversation. */
  const send = (text: string, done: () => void) => {
    const body = withPage(text, page);
    if (id !== null) {
      message.mutate({ id, text: body }, { onSuccess: done, onError: fail("The message was not sent.") });
      return;
    }
    if (key === null) return;
    start.mutate(
      { kind: ASSISTANT_KIND, title: SUPPORT_TITLE },
      {
        onSuccess: (session) => {
          keep(key, session.id);
          message.mutate({ id: session.id, text: body }, { onSuccess: done, onError: fail("The message was not sent.") });
        },
        onError: fail("Support could not start a conversation."),
      },
    );
  };

  const vm: TimelineVm = {
    chat,
    marks,
    stepsError: steps.error,
    copy: (text: string, what: string) => {
      void (navigator.clipboard?.writeText(text) ?? Promise.reject(new Error("no clipboard"))).then(() => notify(`${what} is copied.`), fail(`${what} was not copied.`));
    },
    openCall: () => undefined,
    tools,
    slotSession,
    may,
    decide: (seq: number, approve: boolean, note: string) =>
      actions.decide.mutate({ seq, approve, ...(note.trim() ? { note: note.trim() } : {}) }, { onError: fail("The decision was not sent.") }),
    deciding: actions.decide.isPending,
    control: (command: "pause" | "resume" | "cancel" | "compact" | "unlock") => actions.control.mutate({ command }, { onError: fail(`The ${command} was not sent.`) }),
  };

  return {
    timeline: vm,
    /** The conversation's session, once there is one; its page shows it whole. */
    id,
    /** Whether the person's conversation is still being read back. */
    reading: keptId !== null && kept.isPending,
    /** Whether the assistant works now. */
    working: runs,
    /** Whether the person may send: a member who may only read cannot. */
    maySend: mayWrite && key !== null,
    sending: start.isPending || message.isPending,
    send,
    /** The next message starts a new conversation; this one stays a session. */
    fresh: () => {
      if (key !== null) forget(key);
    },
  };
}

export type SupportVm = ReturnType<typeof useSupportVm>;
