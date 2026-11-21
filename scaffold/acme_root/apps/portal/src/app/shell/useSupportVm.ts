import { useCallback, useMemo, useState } from "react";
import type { agent_sessions } from "@acme/client";
import { useAgentSession, useAsk, useSessionActions, useSteps } from "../../queries/agentSessions";
import type { LiveStream } from "../../queries/live";
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
import { continues, conversationKey, endLine, failedLine, heard, SUPPORT_KIND, SUPPORT_TITLE } from "./supportModel";
import { withPage, type PageContext } from "./supportLinks";

const NOTHING: readonly never[] = [];

/** The support dock's conversation: the person's standing session with the
 * support assistant, read as its page reads it, compact. The id this
 * browser keeps is read back first, and nothing else of it is asked for
 * unless it is the person's own. A question carries the page the person is
 * on, as data, and the first one starts the conversation. The assistant
 * answers in the request that asks it: its text shows as the stream brings
 * it, and the history is read again once the stream ends. One question at a
 * time: the next is sent once the answer is in, or stopped short with its
 * cause shown. */
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
  // The stream is the live view: the history is read when the stream starts
  // and once it ends, and never polled.
  const steps = useSteps(id ?? "", false, id !== null);
  const [asking, setAsking] = useState(false);
  const [live, setLive] = useState<LiveStream[]>([]);
  const [stopped, setStopped] = useState<string | null>(null);
  const now = useNow(asking);
  const actions = useSessionActions(id ?? "");
  const ask = useAsk();
  const fail = useCallback((what: string) => (caught: unknown) => notify(errorMessage(caught, what), { tone: "problem" }), [notify]);

  const tools = slot.tools;
  const gists = useMemo(() => Object.fromEntries(Object.entries(tools).map(([name, tool]) => [name, tool.gist])), [tools]);
  const carded = useMemo(() => new Set(Object.entries(tools).flatMap(([name, tool]) => (tool.card ? [name] : []))), [tools]);
  const history = steps.data;
  const chat = useMemo(
    () =>
      record && history
        ? timeline({ steps: history, live, session: record, held: NOTHING, gists, carded, children: NOTHING, handed: NOTHING, parent: null, now })
        : null,
    [record, history, live, gists, carded, now],
  );
  const marks = useMemo(() => (chat ? outline(chat.entries) : []), [chat]);
  const slotSession: SlotSession | null = useMemo(
    () => (record ? { session: record, calls: chat ? callsOf(chat.entries) : [], running: asking, open: () => undefined } : null),
    [record, chat, asking],
  );
  const mayWrite = me.data?.permissions.includes("write") ?? false;
  const may = record ? allowed(record, mayWrite, me.data?.user.id ?? null) : null;

  /** Asks what the person typed, with the page they are on; the first
   * question starts the conversation. The draft clears once the question is
   * stored, and stays when it is refused. */
  const send = (text: string, done: () => void) => {
    if (key === null || asking) return;
    const said = withPage(text, page);
    const body = id === null ? { kind: SUPPORT_KIND, title: SUPPORT_TITLE, text: said } : { text: said };
    setAsking(true);
    setStopped(null);
    setLive([]);
    void ask(id, body, (event) => {
      if (event.event === "session") {
        if (id === null) keep(key, (event.data as agent_sessions.QuestionSessionEvent).agent_session_id);
        done();
      } else if (event.event === "text") {
        setLive((held) => heard(held, event.data as agent_sessions.QuestionTextEvent));
      } else if (event.event === "end") {
        setStopped(endLine(event.data as agent_sessions.QuestionEndEvent));
      } else if (event.event === "error") {
        setStopped(failedLine(event.data as agent_sessions.QuestionErrorEvent));
      }
    })
      .catch(fail("The question was not sent."))
      .finally(() => {
        setAsking(false);
        setLive([]);
      });
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
    /** Whether the assistant answers now. */
    working: asking,
    /** Why the last answer stopped short, until the next question. */
    stopped,
    /** Whether the person may send: a member who may only read cannot. */
    maySend: mayWrite && key !== null,
    sending: asking,
    send,
    /** The next question starts a new conversation; this one stays a session. */
    fresh: () => {
      if (key !== null) forget(key);
      setStopped(null);
    },
  };
}

export type SupportVm = ReturnType<typeof useSupportVm>;
