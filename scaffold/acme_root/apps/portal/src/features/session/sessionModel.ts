// Pure: what a session's page says, past its timeline (`timelineModel.ts`).
// The status and why a parked session waits, the composer's words, its
// runs, what it delivered, and what a person may do to it now.
// No React, no fetch.
import type {
  AgentSessionView,
  DeliveryView,
  ExecutionView,
  ParkView,
  SessionModelUsageView,
} from "@acme/client";

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
export function usageLine(usage: SessionModelUsageView): string {
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
    // A session reads pending until its first run parks or ends, so a run
    // may hold it while it is pending: a pause parks it at its next step.
    pause: session.status === "running" || session.status === "pending",
    resume: paused,
    cancel: open && !handedOver,
    compact: session.status === "idle",
    takeControl: !handedOver,
    giveBack: handedOver,
    archive: session.status === "idle" && !session.archived_at,
  };
}

/** A command line's words, or why it is not sent. */
export type SplitCommand = { argv: string[] } | { problem: string };

/** What a backslash escapes inside double quotes; before any other
 * character it stays, as the shell keeps it. */
const ESCAPED_IN_DOUBLE = new Set(["$", "`", '"', "\\", "\n"]);

/** The words a command line is typed in, split as a POSIX shell splits them:
 * at blanks, with a quoted run kept whole. A backslash keeps the character
 * after it as it is outside quotes, and only `$`, a backquote, `"`, and `\`
 * inside double quotes; inside single quotes nothing is escaped. A line with
 * a quote left open, a backslash at its end, or an empty word (`''`) is
 * refused with the reason: the API refuses an empty argument, and a line the
 * shell would read otherwise is never sent. */
export function splitCommand(line: string): SplitCommand {
  const argv: string[] = [];
  let current = "";
  let quote: "'" | '"' | null = null;
  let started = false;
  let escaping = false;
  const end = (): string | null => {
    if (!started) return null;
    if (current === "") return "An empty argument ('' or \"\") is not sent: the API refuses one.";
    argv.push(current);
    current = "";
    started = false;
    return null;
  };
  for (const char of line) {
    if (escaping) {
      escaping = false;
      // A backslash before a newline joins the lines, as the shell does.
      if (char === "\n") continue;
      if (quote === '"' && !ESCAPED_IN_DOUBLE.has(char)) current += "\\";
      current += char;
      started = true;
    } else if (quote === "'") {
      if (char === "'") quote = null;
      else current += char;
    } else if (char === "\\") {
      escaping = true;
    } else if (quote === '"') {
      if (char === '"') quote = null;
      else current += char;
    } else if (char === '"' || char === "'") {
      quote = char;
      started = true;
    } else if (/\s/.test(char)) {
      const problem = end();
      if (problem) return { problem };
    } else {
      current += char;
      started = true;
    }
  }
  if (quote) return { problem: `A ${quote === '"' ? "double" : "single"} quote is not closed.` };
  if (escaping) return { problem: "The line ends with a backslash that escapes nothing." };
  const problem = end();
  if (problem) return { problem };
  if (argv.length === 0) return { problem: "Type a command." };
  return { argv };
}

export interface ComposerWords {
  label: string;
  placeholder: string;
}

const REPLY = 'Reply or steer, e.g. "Also add a test for leap years"';

/** What the composer is for now: an answer while the agent asks, a message
 * that replies or steers otherwise. */
export function composerOf(asking: boolean, reply: string | undefined): ComposerWords {
  return asking ? { label: "Answer", placeholder: "Answer the agent's question" } : { label: "Message", placeholder: reply ?? REPLY };
}

export interface PullRequestBadge {
  /** "#12", or the handle when it names no number. */
  label: string;
  handle: string;
  more: number;
}

/** The pull request the session opened, for its header; null before one. */
export function pullRequestBadge(delivery: Pick<DeliveryView, "work">): PullRequestBadge | null {
  const opened = delivery.work.filter((work) => work.kind === "pull_request").map((work) => work.handle);
  const last = opened[opened.length - 1];
  if (last === undefined) return null;
  const number = /(\d+)\s*$/.exec(last)?.[1];
  return { label: number ? `#${number}` : last, handle: last, more: opened.length - 1 };
}
