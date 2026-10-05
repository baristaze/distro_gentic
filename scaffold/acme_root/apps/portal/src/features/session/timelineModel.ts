// Pure: a session's history as a chat. Its steps become entries: a person's
// bubble, a labelled note for any other sender, a thought, the model's
// prose, one line per tool call with consecutive calls folded into a work
// block, a card where the session asks a person or delivers something, a
// thin line for a control or the loop's life, and a folded line for the
// rest. A stream of a step not stored yet joins at the end, and the step
// that lands replaces it. No React, no fetch.
import type { AgentSessionView, ApprovalView, StepView } from "@acme/client";
import { looksLikeDiff, parseJsonText } from "../../design/kit";
import type { LiveStream } from "../../queries/live";
import { statusWords } from "../../app/shell/shellModel";
import { shortTime } from "../sessions/sessionsModel";

/** What a tool was asked: a JSON object, or null where it is gone. */
export type ToolInput = Readonly<Record<string, unknown>>;

/** How a tool's call reads in one line, given what it was asked and what it
 * answered: the slot's `gist`, by tool name. */
export type Gist = (input: unknown, output: unknown) => string;

/** Where a call stands. `asked`: the model asked and no call is made yet;
 * `held`: it waits for a person's decision; `running`: it runs, or its
 * loop waits; `stopped`: its loop ended before it answered. */
export type CallState = "asked" | "held" | "running" | "done" | "failed" | "denied" | "stopped";

/** One tool call: the model's ask, the engine's call, and the tool's answer,
 * paired by the call's id. */
export interface Call {
  id: string;
  tool: string;
  /** What it was asked; null when its content is gone. */
  input: ToolInput | null;
  /** What it answered; null while it has not. */
  output: string | null;
  /** What it streams while it runs, before its answer is stored. */
  liveOutput: string | null;
  failure: string | null;
  state: CallState;
  /** The seq of the step a click opens: its answer, else its call, else the ask. */
  seq: number;
  /** The seq of the engine's call: what a decision names. */
  requestSeq: number | null;
  startedAt: string;
  endedAt: string | null;
}

export type BodyKind = "markdown" | "json" | "diff" | "log" | "none";

export interface CallLine {
  kind: "call";
  key: string;
  call: Call;
  /** "Ran `pytest -q`", "Edited src/dates.py +3 −1". */
  gist: string;
  /** What the chevron shows inline: a diff of an edit, else its answer. */
  body: string;
  bodyKind: BodyKind;
  /** Whether its body shows what it asked cut short by the view. */
  cut: boolean;
}

export interface ThoughtEntry {
  kind: "thought";
  key: string;
  seq: number | null;
  at: string;
  /** How long the model took, rounded up to a second; null when unknown. */
  seconds: number | null;
  text: string;
  /** A thought that still streams: "Thinking…", open. */
  live: boolean;
}

/** What a work block holds: its calls and the thoughts between them. */
export type WorkItem = CallLine | ThoughtEntry;

export type CardKind = "plan" | "pull_request" | "validation" | "result";

export type Entry =
  | { kind: "person"; key: string; seq: number; at: string; text: string }
  | { kind: "note"; key: string; seq: number; at: string; label: string; text: string }
  | ThoughtEntry
  | { kind: "prose"; key: string; seq: number | null; at: string; text: string; live: boolean }
  | { kind: "work"; key: string; at: string; seconds: number; steps: number; running: boolean; items: WorkItem[] }
  | { kind: "action"; key: string; at: string; line: CallLine; authorizationClass: string }
  | { kind: "ask"; key: string; at: string; question: string; line: CallLine | null; open: boolean; unlock: string | null }
  | { kind: "card"; key: string; at: string; card: CardKind; title: string; facts: string[]; body: string; cut: boolean; line: CallLine }
  | { kind: "subagent"; key: string; at: string; title: string; agent: string; childId: string | null; line: CallLine }
  | { kind: "product"; key: string; at: string; line: CallLine }
  | { kind: "line"; key: string; seq: number; at: string; text: string; tone: "plain" | "accent" | "danger" }
  | { kind: "fold"; key: string; seq: number; at: string; label: string; text: string };

export interface StatusRow {
  text: string;
  /** Whether it waits on a person. */
  needsYou: boolean;
  /** Whether it works now: the line shows a spinner. */
  working: boolean;
}

export interface Timeline {
  entries: Entry[];
  status: StatusRow;
}

export interface TimelineInput {
  steps: readonly StepView[];
  live: readonly LiveStream[];
  session: Pick<AgentSessionView, "status" | "park" | "archived_at">;
  /** The calls the session holds for a person's decision. They count only
   * while it is parked on one: a list read before then is stale. */
  held: readonly Pick<ApprovalView, "seq" | "tool" | "authorization_class">[];
  /** How each tool's call reads: the platform's and the product's. */
  gists: Readonly<Record<string, Gist>>;
  /** The tools whose call the product draws as a card of its own. */
  carded: ReadonlySet<string>;
  now: Date;
}

/** The tools whose call asks a person something. */
export const ASK_TOOLS: ReadonlySet<string> = new Set(["ask_person"]);
/** The tools whose call is a card of its own. */
export const CARD_TOOLS: Readonly<Record<string, CardKind>> = {
  write_plan: "plan",
  open_pull_request: "pull_request",
  validate: "validation",
  submit_result: "result",
};
/** Whether a tool's call starts another session, or hands work to one. */
export const spawns = (tool: string) => tool === "spawn" || tool.startsWith("hand_off");

const words = (value: string) => value.replace(/_/g, " ");
const seconds = (from: string, to: string | Date) => {
  const span = ((typeof to === "string" ? Date.parse(to) : to.getTime()) - Date.parse(from)) / 1000;
  return Number.isFinite(span) ? Math.max(0, span) : 0;
};

/** The most characters one string of a tool use's input carries in a
 * step's view: the API cuts a longer one there and ends it in an ellipsis. */
export const MAX_SHOWN = 4096;

/** What a body or a card says under what the view cut short. */
export const CUT_NOTE = "Cut at 4,096 characters: the rest is not shown.";

/** Whether the view cut a string of a tool use's input: it holds more
 * characters than the view carries, counted as the API counts them. */
export function isCut(text: string): boolean {
  return text.length > MAX_SHOWN && Array.from(text).length > MAX_SHOWN;
}

/** "4s", "1m 12s", "2h 5m". */
export function duration(total: number): string {
  const s = Math.max(1, Math.round(total));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function bodyKindOf(text: string): BodyKind {
  if (!text.trim()) return "none";
  if (looksLikeDiff(text)) return "diff";
  if (parseJsonText(text) !== undefined) return "json";
  return "log";
}

const str = (value: unknown): string | null => (typeof value === "string" ? value : null);
const field = (input: unknown, ...names: string[]): string | null => {
  if (!input || typeof input !== "object") return null;
  for (const name of names) {
    const found = str((input as Record<string, unknown>)[name]);
    if (found !== null) return found;
  }
  return null;
};

/** A string's first line, cut to fit one row. */
export function oneLine(text: string, max = 96): string {
  const first = text.split("\n").find((line) => line.trim()) ?? "";
  const cut = first.trim();
  return cut.length > max ? `${cut.slice(0, max - 1)}…` : cut;
}

/** How many lines a text holds; a last newline ends a line, and starts none. */
export function lineCount(text: string): number {
  return text === "" ? 0 : text.replace(/\n$/, "").split("\n").length;
}

/** The lines a change adds and removes: "+3 −1"; nothing when the view
 * cut either side, whose lines it cannot count. */
export function counts(removed: string, added: string): string {
  if (isCut(removed) || isCut(added)) return "";
  return `+${lineCount(added)} −${lineCount(removed)}`;
}

/** An edit's text as a unified diff of one hunk, so it reads as a diff. */
export function editDiff(path: string, removed: string, added: string): string {
  const side = (text: string, mark: string) => (text === "" ? [] : text.replace(/\n$/, "").split("\n").map((line) => `${mark}${line}`));
  const minus = side(removed, "-");
  const plus = side(added, "+");
  return [`--- a/${path}`, `+++ b/${path}`, `@@ -1,${minus.length} +1,${plus.length} @@`, ...minus, ...plus].join("\n");
}

/** The default line of a tool no gist names: its name in words and the
 * first string it was asked. */
function plainGist(tool: string, input: ToolInput | null): string {
  const first = input ? Object.values(input).find((value) => typeof value === "string") : undefined;
  return typeof first === "string" && first.trim() ? `${words(tool)}: ${oneLine(first, 72)}` : words(tool);
}

/** A call as its line reads. */
export function callLine(call: Call, gists: Readonly<Record<string, Gist>>): CallLine {
  const gist = gists[call.tool];
  let line: string;
  try {
    line = gist ? gist(call.input ?? {}, call.output) : plainGist(call.tool, call.input);
  } catch {
    line = plainGist(call.tool, call.input);
  }
  const edit = editOf(call);
  const body = edit ? editDiff(edit.path, edit.removed, edit.added) : outputText(call.output ?? call.liveOutput ?? "");
  return { kind: "call", key: `call-${call.id}`, call, gist: line || words(call.tool), body, bodyKind: edit ? "diff" : bodyKindOf(body), cut: edit?.cut ?? false };
}

/** What an edit or a write changed, from what it was asked, and whether the
 * view cut it short. */
export function editOf(call: Pick<Call, "tool" | "input">): { path: string; removed: string; added: string; cut: boolean } | null {
  const path = field(call.input, "path");
  if (path === null) return null;
  const edit = (removed: string, added: string) => ({ path, removed, added, cut: isCut(removed) || isCut(added) });
  if (call.tool === "edit_file") {
    const added = field(call.input, "new_text");
    return added === null ? null : edit(field(call.input, "old_text") ?? "", added);
  }
  if (call.tool === "write_file") {
    const added = field(call.input, "text");
    return added === null ? null : edit("", added);
  }
  return null;
}

/** A command's answer reads as what it printed; any other answer as it is. */
export function outputText(output: string): string {
  const answer = parseJsonText(output);
  if (answer && typeof answer === "object" && ("stdout" in answer || "stderr" in answer)) {
    const said = answer as { stdout?: unknown; stderr?: unknown; exit_code?: unknown };
    const printed = [str(said.stdout), str(said.stderr)].filter((text): text is string => !!text).join("");
    return typeof said.exit_code === "number" && said.exit_code !== 0 ? `${printed}${printed.endsWith("\n") || !printed ? "" : "\n"}exit ${said.exit_code}` : printed;
  }
  return output;
}

/** Who a message is from, when it is not a person: its card's label. */
export function noteLabel(step: Pick<StepView, "actor" | "origin">): string | null {
  if (step.actor === "person") return null;
  if (step.origin === "automation") return "From an automation";
  if (step.origin === "parent") return "From the parent agent";
  if (step.actor === "program") return "From a program";
  if (step.actor === "external" || step.origin === "integration") return "From an integration";
  if (step.actor === "engine") return "From the engine";
  return "From an agent";
}

const ACTORS: Record<StepView["actor"], string> = {
  person: "A person",
  program: "A program",
  agent: "The agent",
  model: "The model",
  engine: "The engine",
  external: "Something outside",
};

/** A control as its thin line reads: "A person paused it". */
export function controlLine(step: Pick<StepView, "actor" | "command" | "text">): string {
  const who = ACTORS[step.actor];
  const note = step.text.trim() ? `: “${oneLine(step.text, 80)}”` : "";
  switch (step.command) {
    case "pause":
      return `${who} paused it`;
    case "resume":
      return `${who} resumed it`;
    case "cancel":
      return `${who} ended this run`;
    case "interrupt":
      return `${who} stopped the running tool`;
    case "compact":
      return `${who} asked to compact the history`;
    case "approve":
      return `${who} approved a call${note}`;
    case "deny":
      return `${who} denied a call${note}`;
    case "unlock":
      return `${who} cleared what it waited on`;
    default:
      return `${who} sent a control`;
  }
}

/** A park as its thin line reads: "Waiting for a workspace · retries 10:42". */
export function parkedLine(park: NonNullable<StepView["park"]>): string {
  const said = statusWords({ status: "parked", park, archived_at: null });
  return park.retry_at ? `${said} · retries ${shortTime(park.retry_at)}` : said;
}

const OUTCOMES: Record<string, "plain" | "accent" | "danger"> = {
  succeeded: "accent",
  failed: "danger",
  errored: "danger",
  cancelled: "plain",
  inconclusive: "plain",
};

/** Each call the history holds, by the id the model gave it. */
function pairCalls(input: TimelineInput, loopEnded: ReadonlySet<string>): Map<string, Call> {
  const { steps, held, session } = input;
  const calls = new Map<string, Call>();
  const requests = new Map<string, StepView>();
  for (const step of steps) {
    if (step.type === "model_response") {
      for (const use of step.tool_uses) {
        calls.set(use.id, {
          id: use.id,
          tool: use.name,
          input: use.input,
          output: null,
          liveOutput: null,
          failure: null,
          state: "asked",
          seq: step.seq,
          requestSeq: null,
          startedAt: step.created_at,
          endedAt: null,
        });
      }
    } else if (step.type === "tool_request") {
      requests.set(step.id, step);
      const id = step.tool_use_id ?? `seq-${step.seq}`;
      const call = calls.get(id) ?? {
        id,
        tool: step.tool ?? "tool",
        input: null,
        output: null,
        liveOutput: null,
        failure: null,
        state: "asked" as CallState,
        seq: step.seq,
        requestSeq: null,
        startedAt: step.created_at,
        endedAt: null,
      };
      calls.set(id, { ...call, requestSeq: step.seq, seq: step.seq, startedAt: step.created_at, state: "running" });
    } else if (step.type === "tool_response") {
      const request = step.responds_to ? requests.get(step.responds_to) : undefined;
      const id = request?.tool_use_id ?? step.tool_use_id ?? `seq-${step.seq}`;
      const call = calls.get(id);
      if (!call) continue;
      calls.set(id, {
        ...call,
        output: step.text,
        failure: step.failure,
        state: step.failure === "denied" ? "denied" : step.failure ? "failed" : "done",
        seq: step.seq,
        endedAt: step.created_at,
      });
    }
  }
  const heldSeqs = new Set(held.map((call) => call.seq));
  for (const [id, call] of calls) {
    if (call.state !== "running" && call.state !== "asked") continue;
    if (call.requestSeq !== null && heldSeqs.has(call.requestSeq)) calls.set(id, { ...call, state: "held" });
    else if (session.status === "idle" || loopEnded.has(id)) calls.set(id, { ...call, state: "stopped" });
  }
  return calls;
}

/** Whether a session waits for a person's decision on a call it holds. */
function onApproval(session: TimelineInput["session"]): boolean {
  return session.status === "parked" && session.park?.reason === "person" && session.park.unlock === "approval";
}

/** The session's history as entries, with the streams of the steps not
 * stored yet at the end, and the status line under them. The calls it
 * holds count only while it is parked on them: once a decision made
 * elsewhere moves it on, a list read before asks for nothing. */
export function timeline(given: TimelineInput): Timeline {
  const input = onApproval(given.session) ? given : { ...given, held: [] };
  const { steps, gists, now, session } = input;
  const running = session.status === "running" || session.status === "pending";
  // A call whose loop ended before it answered is over, though no step says so.
  const loopEnded = new Set<string>();
  const openByLoop = new Map<string, string[]>();
  for (const step of steps) {
    if (step.type === "model_response") openByLoop.set(step.loop_id, [...(openByLoop.get(step.loop_id) ?? []), ...step.tool_uses.map((use) => use.id)]);
    if (step.type === "loop_ended") for (const id of openByLoop.get(step.loop_id) ?? []) loopEnded.add(id);
  }
  const calls = pairCalls(input, loopEnded);
  const heldBySeq = new Map(input.held.map((call) => [call.seq, call]));
  const requestsAt = new Map(steps.filter((step) => step.type === "model_request").map((step) => [step.id, step.created_at]));
  const loopStarts = new Map<string, string>();
  for (const step of steps) if (!loopStarts.has(step.loop_id)) loopStarts.set(step.loop_id, step.created_at);
  const stored = new Set(steps.map((step) => step.id));

  const entries: Entry[] = [];
  let work: Extract<Entry, { kind: "work" }> | null = null;
  let workEnd: string | Date = "";
  const close = () => {
    work = null;
  };
  const toWork = (item: WorkItem, start: string, end: string | Date) => {
    if (!work) {
      work = { kind: "work", key: `work-${item.key}`, at: start, seconds: 0, steps: 0, running: false, items: [] };
      entries.push(work);
    }
    work.items.push(item);
    if (item.kind === "call") work.steps += 1;
    workEnd = end;
    work.seconds = seconds(work.at, workEnd);
  };
  const placeCall = (call: Call) => {
    const line = callLine(call, gists);
    if (input.carded.has(call.tool) && call.state !== "held") {
      close();
      entries.push({ kind: "product", key: `product-${call.id}`, at: call.startedAt, line });
      return;
    }
    if (call.state === "held") {
      close();
      const asked = call.requestSeq !== null ? heldBySeq.get(call.requestSeq) : undefined;
      entries.push({ kind: "action", key: `action-${call.id}`, at: call.startedAt, line, authorizationClass: asked?.authorization_class ?? "" });
      return;
    }
    if (ASK_TOOLS.has(call.tool)) {
      close();
      const question = field(call.input, "question", "text", "prompt") ?? "";
      // It is open until a message follows it or its loop ends.
      const answered = steps.some((step) => step.type === "message" && step.seq > call.seq);
      entries.push({ kind: "ask", key: `ask-${call.id}`, at: call.startedAt, question, line, open: !answered && call.state !== "stopped" && !loopEnded.has(call.id), unlock: null });
      return;
    }
    const card = CARD_TOOLS[call.tool];
    if (card) {
      close();
      entries.push({ kind: "card", key: `card-${call.id}`, at: call.startedAt, card, ...cardOf(card, call), line });
      return;
    }
    if (spawns(call.tool)) {
      close();
      entries.push({
        kind: "subagent",
        key: `sub-${call.id}`,
        at: call.startedAt,
        title: field(call.input, "title", "objective") ?? "A sub-agent",
        agent: call.tool.startsWith("hand_off_to_") ? words(call.tool.slice("hand_off_to_".length)) : (field(call.input, "kind") ?? "agent"),
        childId: childOf(call.output),
        line,
      });
      return;
    }
    toWork(line, call.startedAt, call.endedAt ?? (call.state === "running" || call.state === "asked" ? now : call.startedAt));
  };

  for (const step of steps) {
    const key = `step-${step.seq}`;
    switch (step.type) {
      case "message": {
        close();
        const label = noteLabel(step);
        if (label === null) entries.push({ kind: "person", key, seq: step.seq, at: step.created_at, text: step.text });
        else entries.push({ kind: "note", key, seq: step.seq, at: step.created_at, label, text: step.text });
        break;
      }
      case "model_request":
        break;
      case "model_response": {
        const asked = step.responds_to ? requestsAt.get(step.responds_to) : undefined;
        if (step.thinking.trim()) {
          const thought: ThoughtEntry = {
            kind: "thought",
            key: `thought-${step.seq}`,
            seq: step.seq,
            at: step.created_at,
            seconds: asked ? seconds(asked, step.created_at) : null,
            text: step.thinking,
            live: false,
          };
          // A thought between calls stays in their block; one before words stands alone.
          if (work && !step.text.trim()) toWork(thought, step.created_at, step.created_at);
          else {
            close();
            entries.push(thought);
          }
        }
        if (step.text.trim()) {
          close();
          entries.push({ kind: "prose", key, seq: step.seq, at: step.created_at, text: step.text, live: false });
        }
        for (const use of step.tool_uses) {
          const call = calls.get(use.id);
          if (call) placeCall(call);
        }
        break;
      }
      case "tool_request": {
        // A call whose ask is gone with its content still has its line.
        const call = calls.get(step.tool_use_id ?? `seq-${step.seq}`);
        if (call && call.input === null && call.requestSeq === step.seq) placeCall(call);
        break;
      }
      case "tool_response":
        break;
      case "control":
        close();
        entries.push({ kind: "line", key, seq: step.seq, at: step.created_at, text: controlLine(step), tone: "plain" });
        break;
      case "parked":
        close();
        if (step.park) entries.push({ kind: "line", key, seq: step.seq, at: step.created_at, text: parkedLine(step.park), tone: "plain" });
        break;
      case "resumed":
        close();
        entries.push({ kind: "line", key, seq: step.seq, at: step.created_at, text: "Resumed", tone: "plain" });
        break;
      case "loop_ended": {
        close();
        const outcome = step.outcome ?? "ended";
        const took = duration(seconds(loopStarts.get(step.loop_id) ?? step.created_at, step.created_at));
        entries.push({ kind: "line", key, seq: step.seq, at: step.created_at, text: `Run ended: ${outcome} · ${took}`, tone: OUTCOMES[outcome] ?? "plain" });
        break;
      }
      case "summary":
        close();
        entries.push({ kind: "fold", key, seq: step.seq, at: step.created_at, label: "Summarized the history", text: step.text });
        break;
      case "switched":
        close();
        entries.push({ kind: "fold", key, seq: step.seq, at: step.created_at, label: "Switched to a new version of its agent", text: step.text });
        break;
      case "environment_changed":
        close();
        entries.push({ kind: "fold", key, seq: step.seq, at: step.created_at, label: "Its environment changed", text: step.text });
        break;
      case "event":
        close();
        entries.push({ kind: "fold", key, seq: step.seq, at: step.created_at, label: noteLabel(step) === "From the engine" ? "A notice from the engine" : "An event arrived", text: step.text });
        break;
    }
  }

  // The streams of steps not stored yet, in the order they opened.
  const openCalls = [...calls.values()].filter((call) => call.state === "running");
  for (const stream of input.live) {
    if (stored.has(stream.stepId)) continue;
    stream.runs.forEach((run, index) => {
      const key = `live-${stream.stepId}-${index}`;
      const at = now.toISOString();
      if (run.kind === "thinking") {
        const thought: ThoughtEntry = { kind: "thought", key, seq: null, at, seconds: null, text: run.text, live: true };
        if (work) toWork(thought, at, now);
        else entries.push(thought);
      } else if (run.kind === "text") {
        close();
        entries.push({ kind: "prose", key, seq: null, at, text: run.text, live: true });
      } else if (run.kind === "tool_input") {
        const call: Call = {
          id: run.toolUseId ?? key,
          tool: run.tool ?? "tool",
          input: null,
          output: null,
          liveOutput: null,
          failure: null,
          state: "asked",
          seq: -1,
          requestSeq: null,
          startedAt: at,
          endedAt: null,
        };
        const line = callLine(call, gists);
        toWork({ ...line, key, gist: `${line.gist}…`, body: run.text, bodyKind: "log" }, at, now);
      } else {
        const target =
          openCalls.find((call) => run.toolUseId !== null && call.id === run.toolUseId) ??
          [...openCalls].reverse().find((call) => run.tool !== null && call.tool === run.tool) ??
          openCalls[openCalls.length - 1];
        if (target) target.liveOutput = (target.liveOutput ?? "") + run.text;
      }
    });
  }
  // A running call's line shows what it streams, beneath it.
  for (const entry of entries) {
    if (entry.kind !== "work") continue;
    entry.items = entry.items.map((item) => (item.kind === "call" && item.call.liveOutput && item.call.output === null ? callLine(item.call, gists) : item));
  }
  const last = entries[entries.length - 1];
  if (last?.kind === "work" && running) {
    last.running = true;
    last.seconds = seconds(last.at, now);
  }
  // A park only a person clears, past a decision or an answer, asks for its
  // unlock in a card of its own at the end.
  const park = session.status === "parked" ? session.park : null;
  if (park && park.reason === "person" && park.unlock !== "answer" && park.unlock !== "approval") {
    const at = steps[steps.length - 1]?.created_at ?? now.toISOString();
    entries.push({ kind: "ask", key: `unlock-${park.unlock}`, at, question: statusWords(session), line: null, open: true, unlock: park.unlock });
  }
  return { entries, status: statusRow(input, entries) };
}

function cardOf(card: CardKind, call: Call): { title: string; facts: string[]; body: string; cut: boolean } {
  const answer = parseJsonText(call.output ?? "");
  const said = answer && typeof answer === "object" && !Array.isArray(answer) ? (answer as Record<string, unknown>) : {};
  const facts = (...found: (string | null | false)[]) => found.filter((fact): fact is string => !!fact);
  // What it was asked, which the view may cut short.
  const asked = (name: string) => {
    const body = field(call.input, name) ?? "";
    return { body, cut: isCut(body) };
  };
  switch (card) {
    case "plan": {
      // Its answer keeps the plan whole.
      const kept = str(said["plan"]);
      return { title: "Plan", facts: [], ...(kept !== null ? { body: kept, cut: false } : asked("plan")) };
    }
    case "pull_request":
      return {
        title: field(call.input, "title") ?? "Pull request",
        facts: facts(str(said["branch"]), str(said["url"])),
        ...asked("body"),
      };
    case "validation": {
      const runs = Array.isArray(said["runs"]) ? said["runs"].length : null;
      const version = str(said["version"]);
      return {
        title: "Validation",
        facts: facts(runs !== null && `${runs} ${runs === 1 ? "run" : "runs"}`, version && `at ${version.slice(0, 12)}`),
        body: call.output && runs === null ? call.output : "",
        cut: false,
      };
    }
    case "result": {
      const evidence = call.input?.["evidence"];
      const cited = Array.isArray(evidence) ? evidence.length : null;
      return {
        title: "Result",
        facts: facts(field(call.input, "claim") && `claims ${field(call.input, "claim")}`, cited !== null && `${cited} ${cited === 1 ? "record" : "records"} cited`),
        body: call.output ?? "",
        cut: false,
      };
    }
  }
}

/** The id of the session a spawn started, when its answer names one. */
function childOf(output: string | null): string | null {
  const answer = parseJsonText(output ?? "") as Record<string, unknown> | undefined;
  return field(answer, "session_id", "child_id", "id");
}

/** Every call the entries hold, in order: what a product's tab or card reads. */
export function callsOf(entries: readonly Entry[]): Call[] {
  const calls: Call[] = [];
  for (const entry of entries) {
    if (entry.kind === "work") for (const item of entry.items) if (item.kind === "call") calls.push(item.call);
    if (entry.kind === "action" || entry.kind === "card" || entry.kind === "subagent" || entry.kind === "product") calls.push(entry.line.call);
    if (entry.kind === "ask" && entry.line) calls.push(entry.line.call);
  }
  return calls;
}

/** Whether an entry is the agent's question still waiting for an answer: the
 * composer's next message answers it. */
export const answers = (entry: Entry) => entry.kind === "ask" && entry.open && entry.unlock === null;

function statusRow(input: TimelineInput, entries: readonly Entry[]): StatusRow {
  const { session, held } = input;
  if (session.archived_at !== null) return { text: "Archived", needsYou: false, working: false };
  if (held.length > 0) return { text: `Needs you: approve ${held[0]!.tool}`, needsYou: true, working: false };
  const asking = entries.some(answers);
  if (session.status === "parked" && session.park?.reason === "person") {
    return { text: asking ? "Needs you: answer the agent's question" : statusWords(session), needsYou: true, working: false };
  }
  // A session reads pending until its first run parks or ends: once that
  // run streams or writes past its input, it works.
  const last = input.steps[input.steps.length - 1];
  const underway = input.live.length > 0 || (last !== undefined && last.type !== "message");
  if (session.status === "running" || (session.status === "pending" && underway)) return { text: "Working…", needsYou: false, working: true };
  if (session.status === "pending") return { text: "Starting…", needsYou: false, working: true };
  if (session.status === "parked") return { text: session.park ? parkedLine(session.park) : "Waiting", needsYou: false, working: false };
  const ended = [...entries].reverse().find((entry) => entry.kind === "line" && entry.text.startsWith("Run ended"));
  if (ended && ended.kind === "line" && ended.tone === "danger") return { text: ended.text.replace(/^Run ended: /, "Ended: "), needsYou: false, working: false };
  return { text: "Done", needsYou: false, working: false };
}
