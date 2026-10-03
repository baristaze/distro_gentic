// Pure: what a session's page says. The status and why a parked session
// waits, the thread and the timeline its history reads as, its tool calls,
// its runs, what it delivered, and what a person may do to it now. No React,
// no fetch.
import type {
  AgentSessionView,
  ApprovalView,
  DeliveryView,
  ExecutionView,
  ParkView,
  QuestionView,
  SessionUsageView,
  StepView,
  ToolCallView,
} from "@acme/client";
import { looksLikeDiff, parseJsonText } from "../../design/kit";

export type Tone = "plain" | "accent" | "danger";

export interface StatusLine {
  label: string;
  tone: Tone;
}

/** An archived session says so first; otherwise its status, a parked one in
 * the warning tone, a running one in the accent. */
export function statusLine(session: Pick<AgentSessionView, "status" | "archived_at">): StatusLine {
  if (session.archived_at) return { label: "archived", tone: "plain" };
  switch (session.status) {
    case "running":
      return { label: "running", tone: "accent" };
    case "parked":
      return { label: "parked", tone: "danger" };
    case "pending":
      return { label: "pending", tone: "plain" };
    case "idle":
      return { label: "idle", tone: "plain" };
  }
}

const REASONS: Record<ParkView["reason"], string> = {
  person: "It waits on a person.",
  provider: "Its model provider did not answer.",
  budget: "Its budget is spent.",
  resource: "It waits for a resource.",
  job: "It waits for work it started.",
  children: "It waits for the sessions it started.",
  handover: "A person has control.",
  pause: "It is paused.",
};

const UNLOCKS: Record<string, string> = {
  approval: "a decision on the call it holds",
  give_back: "the person in control giving it back",
  step_guard: "lifting its step guard",
  deadline: "moving its deadline",
  principal: "naming a principal for it",
  spender: "a spender for its budget",
  workspace: "its workspace",
  permission: "a permission",
};

/** What a person does to clear a park, when a person clears it. */
export type ParkAction = "decide" | "unlock" | "give_back" | "resume" | null;

export interface ParkLine {
  reason: string;
  /** What clears it, in words. */
  unlock: string;
  /** When it tries again by itself; null when only a person clears it. */
  retryAt: string | null;
  action: ParkAction;
}

export function parkLine(park: ParkView): ParkLine {
  let action: ParkAction = null;
  if (park.reason === "pause") action = "resume";
  else if (park.reason === "handover") action = "give_back";
  else if (park.unlock === "approval") action = "decide";
  else if (park.reason === "person") action = "unlock";
  return {
    reason: REASONS[park.reason],
    unlock: UNLOCKS[park.unlock] ?? park.unlock.replace(/_/g, " "),
    retryAt: park.retry_at,
    action,
  };
}

/** What a session asks of a person now: the calls it holds for a decision,
 * then the parks only an unlock clears, oldest first. */
export interface Ask {
  seq: number;
  kind: "decision" | "unlock";
  what: string;
  at: string;
}

export function asks(approvals: readonly ApprovalView[], questions: readonly QuestionView[]): Ask[] {
  return [
    ...approvals.map((call) => ({
      seq: call.seq,
      kind: "decision" as const,
      what: `Run ${call.tool} (${call.authorization_class.replace(/_/g, " ")})`,
      at: call.requested_at,
    })),
    ...questions.map((question) => ({
      seq: question.seq,
      kind: "unlock" as const,
      what: `Clear it by ${UNLOCKS[question.unlock] ?? question.unlock.replace(/_/g, " ")}`,
      at: question.asked_at,
    })),
  ].sort((a, b) => a.seq - b.seq);
}

export interface ThreadEntry {
  seq: number;
  who: "person" | "agent";
  text: string;
  at: string;
}

/** The conversation: what a person said and what the agent answered, in
 * order. A model answer that only called tools says nothing here. */
export function thread(steps: readonly StepView[]): ThreadEntry[] {
  const entries: ThreadEntry[] = [];
  for (const step of steps) {
    if (step.type === "message") entries.push({ seq: step.seq, who: step.actor === "agent" ? "agent" : "person", text: step.text, at: step.created_at });
    else if (step.type === "model_response" && step.text.trim()) entries.push({ seq: step.seq, who: "agent", text: step.text, at: step.created_at });
  }
  return entries;
}

/** How a step's text reads best. */
export type BodyKind = "markdown" | "json" | "diff" | "log" | "none";

export function bodyKind(step: Pick<StepView, "type" | "text">): BodyKind {
  if (!step.text.trim()) return "none";
  if (step.type === "message" || step.type === "model_response" || step.type === "summary") return "markdown";
  if (looksLikeDiff(step.text)) return "diff";
  if (parseJsonText(step.text) !== undefined) return "json";
  return "log";
}

export interface TimelineEntry {
  seq: number;
  type: StepView["type"];
  at: string;
  title: string;
  detail: string | null;
  tone: Tone;
  body: string;
  bodyKind: BodyKind;
}

const words = (value: string) => value.replace(/_/g, " ");

function titleOf(step: StepView): { title: string; detail: string | null; tone: Tone } {
  switch (step.type) {
    case "message":
      return { title: `Message from ${step.actor === "person" ? "a person" : words(step.actor)}`, detail: `by ${words(step.origin)}`, tone: "plain" };
    case "model_request":
      return { title: "Model called", detail: null, tone: "plain" };
    case "model_response":
      return {
        title: "Model answered",
        detail: step.tools.length > 0 ? `called ${step.tools.join(", ")}` : step.stop_reason ? words(step.stop_reason) : null,
        tone: step.stop_reason === "refusal" || step.stop_reason === "content_filter" ? "danger" : "plain",
      };
    case "tool_request":
      return { title: `Called ${step.tool ?? "a tool"}`, detail: null, tone: "plain" };
    case "tool_response":
      return step.failure
        ? { title: `${step.tool ?? "A tool"} failed`, detail: words(step.failure), tone: "danger" }
        : { title: `${step.tool ?? "A tool"} answered`, detail: null, tone: "plain" };
    case "control":
      return { title: `Control: ${words(step.command ?? "unknown")}`, detail: null, tone: "plain" };
    case "parked":
      return step.park
        ? { title: "Parked", detail: `${parkLine(step.park).reason} Cleared by ${parkLine(step.park).unlock}.`, tone: "accent" }
        : { title: "Parked", detail: null, tone: "accent" };
    case "resumed":
      return { title: "Resumed", detail: null, tone: "plain" };
    case "loop_ended":
      return {
        title: `Loop ended${step.outcome ? `: ${step.outcome}` : ""}`,
        detail: null,
        tone: step.outcome === "failed" || step.outcome === "errored" ? "danger" : step.outcome === "succeeded" ? "accent" : "plain",
      };
    case "summary":
      return { title: "Summary", detail: null, tone: "plain" };
    case "switched":
      return { title: "Switched model", detail: null, tone: "plain" };
    case "environment_changed":
      return { title: "Environment changed", detail: null, tone: "plain" };
    case "event":
      return { title: "Event", detail: null, tone: "plain" };
  }
}

/** Every step as one entry of the timeline, in order. */
export function timeline(steps: readonly StepView[]): TimelineEntry[] {
  return steps.map((step) => ({
    seq: step.seq,
    type: step.type,
    at: step.created_at,
    ...titleOf(step),
    body: step.text,
    bodyKind: bodyKind(step),
  }));
}

export interface ToolCallRow {
  seq: number;
  tool: string;
  state: string;
  tone: Tone;
  requestedAt: string;
  decidedBy: string | null;
}

export function toolCallRow(call: ToolCallView): ToolCallRow {
  let state = "running";
  let tone: Tone = "accent";
  if (call.decision === "pending") [state, tone] = ["waits for a decision", "danger"];
  else if (call.decision === "denied" || call.decision === "expired") [state, tone] = [call.decision, "danger"];
  else if (call.failure) [state, tone] = [`failed: ${words(call.failure)}`, "danger"];
  else if (call.responded_at) [state, tone] = ["answered", "plain"];
  return { seq: call.seq, tool: call.tool, state, tone, requestedAt: call.requested_at, decidedBy: call.decided_by };
}

export interface RunRow {
  id: string;
  check: string;
  purpose: string;
  outcome: string;
  tone: Tone;
  provenance: string;
  cases: string;
  version: string;
  where: string;
  seconds: number;
}

const PROVENANCE: Record<ExecutionView["provenance"], string> = {
  real: "real",
  twin: "twin, never reported as real",
  double: "test double, never validation",
  unavailable: "unavailable",
};

/** One run of one check, as its row says it: a run against a twin or a
 * double says so beside its outcome. */
export function runRow(run: ExecutionView): RunRow {
  const counts = [
    run.cases.passed ? `${run.cases.passed} passed` : null,
    run.cases.failed ? `${run.cases.failed} failed` : null,
    run.cases.skipped ? `${run.cases.skipped} skipped` : null,
  ].filter(Boolean);
  return {
    id: run.id,
    check: `${run.check} ${run.check_version}`,
    purpose: run.purpose,
    outcome: run.outcome,
    tone: run.outcome === "passed" ? "accent" : run.outcome === "aborted" ? "plain" : "danger",
    provenance: PROVENANCE[run.provenance],
    cases: counts.length > 0 ? counts.join(", ") : "no cases",
    version: `${run.version.slice(0, 12)}${run.dirty ? " (uncommitted changes)" : ""}`,
    where: `${run.host}, ${run.isolation}`,
    seconds: Math.max(0, (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000),
  };
}

export interface DeliveryLines {
  branch: string | null;
  pullRequests: string[];
  branches: string[];
  report: string | null;
}

export function deliveryLines(delivery: DeliveryView): DeliveryLines {
  const report = delivery.report;
  return {
    branch: delivery.branch,
    pullRequests: delivery.work.filter((work) => work.kind === "pull_request").map((work) => work.handle),
    branches: delivery.work.filter((work) => work.kind === "branch").map((work) => work.handle),
    report: report ? `${report.outcome}, ${report.verified ? "verified" : "not verified"}` : null,
  };
}

/** "3 model calls: 1,200 tokens in, 340 out". */
export function usageLine(usage: SessionUsageView): string {
  const count = (n: number) => n.toLocaleString("en-US");
  return `${count(usage.calls)} model ${usage.calls === 1 ? "call" : "calls"}: ${count(usage.input)} tokens in, ${count(usage.output)} out`;
}

/** What a person may do to the session as it stands; a member who may not
 * write may do nothing. */
export interface Allowed {
  send: boolean;
  pause: boolean;
  resume: boolean;
  cancel: boolean;
  compact: boolean;
  takeControl: boolean;
  giveBack: boolean;
  archive: boolean;
}

export function allowed(session: AgentSessionView, mayWrite: boolean): Allowed {
  const handedOver = session.park?.reason === "handover";
  const paused = session.park?.reason === "pause";
  const open = session.status === "running" || session.status === "parked" || session.status === "pending";
  const none: Allowed = { send: false, pause: false, resume: false, cancel: false, compact: false, takeControl: false, giveBack: false, archive: false };
  if (!mayWrite) return none;
  return {
    send: !handedOver,
    pause: session.status === "running",
    resume: paused,
    cancel: open && !handedOver,
    compact: session.status === "idle",
    takeControl: !handedOver,
    giveBack: handedOver,
    archive: session.status === "idle" && !session.archived_at,
  };
}

/** The words a command line is typed in, split as a shell splits them:
 * at spaces, with a quoted run kept whole. */
export function splitCommand(line: string): string[] {
  const argv: string[] = [];
  let current = "";
  let quote: string | null = null;
  let started = false;
  for (const char of line) {
    if (quote) {
      if (char === quote) quote = null;
      else current += char;
    } else if (char === '"' || char === "'") {
      quote = char;
      started = true;
    } else if (/\s/.test(char)) {
      if (started || current) argv.push(current);
      current = "";
      started = false;
    } else current += char;
  }
  if (started || current) argv.push(current);
  return argv;
}

export type SessionTab = "thread" | "timeline" | "tools" | "evidence" | "changes" | "children" | "live";

export const SESSION_TABS: readonly { value: SessionTab; label: string }[] = [
  { value: "thread", label: "Thread" },
  { value: "timeline", label: "Timeline" },
  { value: "tools", label: "Tool calls" },
  { value: "evidence", label: "Evidence" },
  { value: "changes", label: "Changes" },
  { value: "children", label: "Sub-agents" },
  { value: "live", label: "Live" },
];

/** The part of the page the address bar names; the thread otherwise. */
export function sessionTab(value: string | null): SessionTab {
  return SESSION_TABS.find((tab) => tab.value === value)?.value ?? "thread";
}
