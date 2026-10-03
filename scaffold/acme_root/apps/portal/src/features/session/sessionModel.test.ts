import { describe, expect, it } from "vitest";
import type { AgentSessionView, ExecutionView, StepView, ToolCallView } from "@acme/client";
import {
  allowed,
  asks,
  bodyKind,
  deliveryLines,
  parkLine,
  runRow,
  sessionTab,
  splitCommand,
  statusLine,
  thread,
  timeline,
  toolCallRow,
  usageLine,
} from "./sessionModel";

const at = "2026-10-03T10:00:00Z";

function step(seq: number, fields: Partial<StepView>): StepView {
  return {
    id: `step-${seq}`,
    seq,
    loop_id: "loop-1",
    type: "event",
    actor: "engine",
    origin: "engine",
    text: "",
    created_at: at,
    command: null,
    failure: null,
    outcome: null,
    park: null,
    refs: [],
    responds_to: null,
    stop_reason: null,
    tool: null,
    tools: [],
    ...fields,
  };
}

const session: AgentSessionView = {
  id: "s1",
  root_id: "s1",
  parent_id: null,
  kind: "assistant",
  kind_version: 1,
  title: "Tidy the docs",
  status: "idle",
  park: null,
  created_at: at,
  created_by: "u1",
  archived_at: null,
  deleted_at: null,
};

const HISTORY = [
  step(1, { type: "message", actor: "person", origin: "portal", text: "Please **tidy** it." }),
  step(2, { type: "model_request", actor: "engine" }),
  step(3, { type: "model_response", actor: "model", text: "", tools: ["read_file"], stop_reason: "tool_use" }),
  step(4, { type: "tool_request", actor: "agent", tool: "read_file", text: '{"path": "README.md"}' }),
  step(5, { type: "tool_response", actor: "program", tool: "read_file", text: "@@ -1 +1 @@\n-old\n+new" }),
  step(6, { type: "tool_response", actor: "program", tool: "run", failure: "timeout", text: "still going" }),
  step(7, { type: "model_response", actor: "model", text: "Done: the README reads well now.", stop_reason: "end_turn" }),
  step(8, { type: "loop_ended", outcome: "succeeded" }),
];

describe("status and parks", () => {
  it("says archived first, and a parked session in the warning tone", () => {
    expect(statusLine({ status: "parked", archived_at: null })).toEqual({ label: "parked", tone: "danger" });
    expect(statusLine({ status: "idle", archived_at: at })).toEqual({ label: "archived", tone: "plain" });
  });

  it("says why a park waits, what clears it, and the action a person takes", () => {
    expect(parkLine({ reason: "person", unlock: "approval", retry_at: null })).toMatchObject({ action: "decide", unlock: "a decision on the call it holds" });
    expect(parkLine({ reason: "person", unlock: "step_guard", retry_at: null })).toMatchObject({ action: "unlock", unlock: "lifting its step guard" });
    expect(parkLine({ reason: "handover", unlock: "give_back", retry_at: null }).action).toBe("give_back");
    expect(parkLine({ reason: "pause", unlock: "resume", retry_at: null }).action).toBe("resume");
    expect(parkLine({ reason: "provider", unlock: "provider", retry_at: at })).toMatchObject({ action: null, retryAt: at });
  });

  it("lists what the session asks of a person, oldest first", () => {
    const listed = asks(
      [{ seq: 9, session_id: "s1", tool: "deploy", authorization_class: "outward_facing", principal_id: "p", requested_at: at }],
      [{ seq: 4, session_id: "s1", unlock: "deadline", asked_at: at }],
    );
    expect(listed.map((ask) => [ask.seq, ask.kind, ask.what])).toEqual([
      [4, "unlock", "Clear it by moving its deadline"],
      [9, "decision", "Run deploy (outward facing)"],
    ]);
  });
});

describe("the history", () => {
  it("reads the thread as what a person said and what the agent answered", () => {
    expect(thread(HISTORY).map((entry) => [entry.seq, entry.who])).toEqual([
      [1, "person"],
      [7, "agent"],
    ]);
  });

  it("reads every step as a timeline entry with the body kind its text needs", () => {
    const entries = timeline(HISTORY);
    expect(entries.map((entry) => [entry.seq, entry.title, entry.bodyKind])).toEqual([
      [1, "Message from a person", "markdown"],
      [2, "Model called", "none"],
      [3, "Model answered", "none"],
      [4, "Called read_file", "json"],
      [5, "read_file answered", "diff"],
      [6, "run failed", "log"],
      [7, "Model answered", "markdown"],
      [8, "Loop ended: succeeded", "none"],
    ]);
    expect(entries[2]!.detail).toBe("called read_file");
    expect([entries[5]!.tone, entries[5]!.detail]).toEqual(["danger", "timeout"]);
    expect(entries[7]!.tone).toBe("accent");
  });

  it("reads a summary as Markdown and a tool's plain output as a log", () => {
    expect(bodyKind({ type: "summary", text: "# Notes" })).toBe("markdown");
    expect(bodyKind({ type: "tool_response", text: "ok\n" })).toBe("log");
  });

  it("reads a tool's output with lines outside its hunks as a log, so every line is drawn", () => {
    const show = "commit 0123abc\nAuthor: A <a@example.test>\n\n    Tidy\n\ndiff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n";
    expect(bodyKind({ type: "tool_response", text: show })).toBe("log");
    expect(bodyKind({ type: "tool_response", text: "Changed:\n@@ -1 +1 @@\n-old\n+new" })).toBe("log");
  });
});

describe("tool calls, runs, delivery, and usage", () => {
  const call: ToolCallView = {
    seq: 4,
    loop_id: "loop-1",
    tool: "deploy",
    authorization_class: "outward_facing",
    principal_id: "p",
    requested_at: at,
    responded_at: null,
    response_seq: null,
    decision: null,
    decided_by: null,
    failure: null,
  };

  it("says where each tool call stands", () => {
    expect(toolCallRow({ ...call, decision: "pending" })).toMatchObject({ state: "waits for a decision", tone: "danger" });
    expect(toolCallRow({ ...call, failure: "denied", decision: "denied" }).state).toBe("denied");
    expect(toolCallRow({ ...call, responded_at: at, response_seq: 5 }).state).toBe("answered");
    expect(toolCallRow(call).state).toBe("running");
  });

  it("says a run's check, outcome, cases, and a twin's provenance beside it", () => {
    const run: ExecutionView = {
      id: "r1",
      step_id: "step-4",
      validation_id: null,
      purpose: "work",
      check: "unit",
      check_version: "1",
      version: "0123456789abcdef",
      dirty: true,
      executor: "x",
      image: "img",
      host: "h1",
      isolation: "container",
      project: "p",
      provenance: "twin",
      outcome: "failed",
      cases: { passed: 3, failed: 1, skipped: 0 },
      started_at: "2026-10-03T10:00:00Z",
      finished_at: "2026-10-03T10:00:12Z",
      abort: null,
    };
    expect(runRow(run)).toMatchObject({
      check: "unit 1",
      outcome: "failed",
      tone: "danger",
      provenance: "twin, never reported as real",
      cases: "3 passed, 1 failed",
      version: "0123456789ab (uncommitted changes)",
      seconds: 12,
    });
  });

  it("splits delivered work into pull requests and branches, and says the report", () => {
    expect(
      deliveryLines({
        branch: "agent/tidy",
        branch_seen: true,
        project_id: null,
        report: { seq: 8, outcome: "succeeded", verified: false, accepted_at: at },
        work: [
          { kind: "pull_request", handle: "acme/docs#12", bound_at: at },
          { kind: "branch", handle: "acme/docs:agent/tidy", bound_at: at },
        ],
      }),
    ).toEqual({ branch: "agent/tidy", pullRequests: ["acme/docs#12"], branches: ["acme/docs:agent/tidy"], report: "succeeded, not verified" });
  });

  it("counts the model calls and the tokens", () => {
    expect(usageLine({ calls: 1, input: 1200, output: 34, thinking: 0, cache_read: 0, cache_write: 0, fills: [] })).toBe("1 model call: 1,200 tokens in, 34 out");
  });
});

describe("what a person may do", () => {
  it("lets a member who may not write do nothing", () => {
    expect(Object.values(allowed({ ...session, status: "running" }, false)).some(Boolean)).toBe(false);
  });

  it("offers pause while it runs, resume while paused, and give back while a person has control", () => {
    expect(allowed({ ...session, status: "running" }, true)).toMatchObject({ pause: true, resume: false, cancel: true, archive: false });
    expect(allowed({ ...session, status: "parked", park: { reason: "pause", unlock: "resume", retry_at: null } }, true)).toMatchObject({ resume: true, pause: false });
    expect(allowed({ ...session, status: "parked", park: { reason: "handover", unlock: "give_back", retry_at: null } }, true)).toMatchObject({
      giveBack: true,
      takeControl: false,
      send: false,
    });
    expect(allowed(session, true)).toMatchObject({ archive: true, compact: true });
  });

  it("splits a typed command at spaces and keeps a quoted run whole", () => {
    expect(splitCommand(`git commit -m "a message"`)).toEqual({ argv: ["git", "commit", "-m", "a message"] });
    expect(splitCommand("  ls   -la ")).toEqual({ argv: ["ls", "-la"] });
    expect(splitCommand(`echo 'it''s' "x"y`)).toEqual({ argv: ["echo", "its", "xy"] });
  });

  it("honours a backslash as the shell does: outside quotes and in double quotes, never in single ones", () => {
    expect(splitCommand("rm notes\\ v2.txt")).toEqual({ argv: ["rm", "notes v2.txt"] });
    expect(splitCommand(`git commit -m "say \\"hi\\""`)).toEqual({ argv: ["git", "commit", "-m", 'say "hi"'] });
    expect(splitCommand(`echo "a\\b" 'c\\d' \\'`)).toEqual({ argv: ["echo", "a\\b", "c\\d", "'"] });
  });

  it("refuses an open quote, a trailing backslash, and an empty argument, with the reason", () => {
    expect(splitCommand(`echo "unterminated`)).toEqual({ problem: "A double quote is not closed." });
    expect(splitCommand(`echo 'unterminated`)).toEqual({ problem: "A single quote is not closed." });
    expect(splitCommand("ls \\")).toEqual({ problem: "The line ends with a backslash that escapes nothing." });
    expect(splitCommand("git commit -m ''")).toEqual({ problem: `An empty argument ('' or "") is not sent: the API refuses one.` });
    expect(splitCommand("   ")).toEqual({ problem: "Type a command." });
  });
});

describe("the page's parts", () => {
  it("opens the part the address bar names, and the thread otherwise", () => {
    expect([sessionTab("evidence"), sessionTab("nope"), sessionTab(null)]).toEqual(["evidence", "thread", "thread"]);
  });
});
