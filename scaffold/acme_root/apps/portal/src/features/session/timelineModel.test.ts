// A session's history as a chat: each kind of step reads as its row, from
// steps as the API answers them.
import { describe, expect, it } from "vitest";
import type { StepView } from "@acme/client";
import type { LiveStream } from "../../queries/live";
import { commandLine, PLATFORM_GISTS } from "./toolGists";
import { answers, bodyKindOf, callsOf, duration, editDiff, isCut, MAX_SHOWN, timeline, type Entry, type TimelineInput } from "./timelineModel";

const T0 = Date.parse("2026-10-05T10:00:00Z");
const at = (s: number) => new Date(T0 + s * 1000).toISOString();

let seq = 0;
function step(fields: Partial<StepView> & Pick<StepView, "type">, second = seq): StepView {
  seq += 1;
  return {
    id: `step-${seq}`,
    seq,
    loop_id: "loop-1",
    actor: "engine",
    origin: "engine",
    text: "",
    thinking: "",
    tool_uses: [],
    tool_use_id: null,
    agent: null,
    created_at: at(second),
    command: null,
    failure: null,
    outcome: null,
    park: null,
    refs: [],
    responds_to: null,
    stop_reason: null,
    tool: null,
    tools: [],
    usage: null,
    ...fields,
  };
}

const said = (text: string, actor: StepView["actor"] = "person", origin: StepView["origin"] = "portal") =>
  step({ type: "message", actor, origin, text });
const request = (second: number) => step({ type: "model_request", actor: "engine" }, second);
function response(asked: StepView, second: number, fields: Partial<StepView>): StepView {
  return step({ type: "model_response", actor: "model", responds_to: asked.id, ...fields }, second);
}
const toolUse = (id: string, name: string, input: Record<string, unknown>) => ({ id, name, input });
function call(by: StepView, id: string, tool: string, second: number): StepView {
  return step({ type: "tool_request", actor: "agent", refs: [by.id], tool, tool_use_id: id }, second);
}
function answer(asked: StepView, text: string, second: number, failure: StepView["failure"] = null): StepView {
  return step({ type: "tool_response", responds_to: asked.id, tool: asked.tool, tool_use_id: asked.tool_use_id, text, failure }, second);
}

function read(steps: StepView[], over: Partial<TimelineInput> = {}) {
  return timeline({
    steps,
    live: [],
    session: { status: "idle", park: null, archived_at: null },
    held: [],
    gists: PLATFORM_GISTS,
    carded: new Set(),
    now: new Date(T0 + 600_000),
    ...over,
  });
}
const kinds = (entries: Entry[]) => entries.map((entry) => entry.kind);
function only<K extends Entry["kind"]>(entries: Entry[], kind: K): Extract<Entry, { kind: K }> {
  const found = entries.filter((entry) => entry.kind === kind);
  expect(found).toHaveLength(1);
  return found[0] as Extract<Entry, { kind: K }>;
}

/** A turn: the model thinks, says a line, and runs `pytest -q`, which fails. */
function turn() {
  const asked = request(0);
  const thought = response(asked, 4, {
    thinking: "The failing test names the parser.",
    text: "I'll run the tests first.",
    tool_uses: [toolUse("u1", "run_command", { argv: ["pytest", "-q"] })],
  });
  const ran = call(thought, "u1", "run_command", 5);
  const failed = answer(ran, JSON.stringify({ exit_code: 1, stdout: "1 failed\n", stderr: "" }), 9);
  return [asked, thought, ran, failed];
}

describe("timeline", () => {
  it("draws a person's message as a bubble, and any other sender's as a labelled note", () => {
    const { entries } = read([
      said("Fix the failing test."),
      said("Nightly run", "program", "automation"),
      said("Port the parser", "agent", "parent"),
      said("A key's call", "program", "api"),
    ]);
    expect(kinds(entries)).toEqual(["person", "note", "note", "note"]);
    expect(entries.map((entry) => (entry.kind === "note" ? entry.label : entry.kind))).toEqual([
      "person",
      "From an automation",
      "From the parent agent",
      "From a program",
    ]);
  });

  it("draws a thought collapsed with how long it took, the model's text as prose, and a call as one line in a work block", () => {
    const { entries } = read(turn());
    expect(kinds(entries)).toEqual(["thought", "prose", "work"]);
    expect(only(entries, "thought")).toMatchObject({ seconds: 4, text: "The failing test names the parser.", live: false });
    expect(only(entries, "prose").text).toBe("I'll run the tests first.");
    const work = only(entries, "work");
    expect(work).toMatchObject({ steps: 1, running: false, seconds: 4 });
    expect(work.items[0]).toMatchObject({ kind: "call", gist: "Ran `pytest -q` · exit 1", body: "1 failed\nexit 1", bodyKind: "log" });
    expect(work.items[0]!.kind === "call" && work.items[0]!.call.state).toBe("done");
  });

  it("folds consecutive calls into one block, a thought between them inside it, and shows an edit as its diff", () => {
    const steps = turn();
    const asked = request(10);
    const next = response(asked, 12, {
      thinking: "The date is parsed as a local time.",
      tool_uses: [toolUse("u2", "edit_file", { path: "src/dates.py", old_text: "parse(x)\n", new_text: "parse(x, tz=UTC)\nreturn x\n" })],
    });
    const edited = call(next, "u2", "edit_file", 13);
    const ok = answer(edited, JSON.stringify({ path: "src/dates.py", line: 4, lines: 2, size: 80 }), 14);
    const { entries } = read([...steps, asked, next, edited, ok]);
    expect(kinds(entries)).toEqual(["thought", "prose", "work"]);
    const work = only(entries, "work");
    expect(work.steps).toBe(2);
    expect(work.items.map((item) => item.kind)).toEqual(["call", "thought", "call"]);
    expect(work.items[2]).toMatchObject({
      gist: "Edited src/dates.py +2 −1",
      bodyKind: "diff",
      body: editDiff("src/dates.py", "parse(x)\n", "parse(x, tz=UTC)\nreturn x\n"),
    });
  });

  it("keeps a block open while the session runs, timed to now", () => {
    const steps = turn().slice(0, 3);
    const { entries, status } = read(steps, { session: { status: "running", park: null, archived_at: null }, now: new Date(T0 + 65_000) });
    const work = only(entries, "work");
    expect(work).toMatchObject({ running: true, seconds: 60 });
    expect(work.items[0]!.kind === "call" && work.items[0]!.call.state).toBe("running");
    expect(status).toEqual({ text: "Working…", needsYou: false, working: true });
  });

  it("reads a pending session as working once its run writes past its input", () => {
    const pending = { status: "pending" as const, park: null, archived_at: null };
    expect(read([], { session: pending }).status.text).toBe("Starting…");
    expect(read(turn().slice(0, 3), { session: pending }).status.text).toBe("Working…");
  });

  it("draws a call held for a decision as an action card, and the status line asks for it", () => {
    const steps = turn().slice(0, 3);
    const ran = steps[2]!;
    const { entries, status } = read(steps, {
      session: { status: "parked", park: { reason: "person", unlock: "approval", retry_at: null }, archived_at: null },
      held: [{ seq: ran.seq, tool: "run_command", authorization_class: "execute" }],
    });
    expect(kinds(entries)).toEqual(["thought", "prose", "action"]);
    expect(only(entries, "action")).toMatchObject({ authorizationClass: "execute", line: { gist: "Run `pytest -q`", call: { requestSeq: ran.seq, state: "held" } } });
    expect(status).toEqual({ text: "Needs you: approve run_command", needsYou: true, working: false });
  });

  it("reads a session no longer parked on a decision by its own status, whatever a stale list of held calls says", () => {
    const steps = turn().slice(0, 3);
    const stale = [{ seq: steps[2]!.seq, tool: "run_command", authorization_class: "execute" }];
    const decided = read(steps, { session: { status: "running", park: null, archived_at: null }, held: stale });
    expect(kinds(decided.entries)).toEqual(["thought", "prose", "work"]);
    expect(decided.status).toEqual({ text: "Working…", needsYou: false, working: true });
    const paused = read(steps, { session: { status: "parked", park: { reason: "pause", unlock: "resume", retry_at: null }, archived_at: null }, held: stale });
    expect(kinds(paused.entries)).not.toContain("action");
    expect(paused.status.text).not.toMatch(/approve/);
  });

  it("draws ask_person as the agent's question, open until it is answered", () => {
    const asked = request(0);
    const asks = response(asked, 1, { tool_uses: [toolUse("q1", "ask_person", { question: "Shall I add a leap-year test too?" })] });
    const made = call(asks, "q1", "ask_person", 2);
    const echoed = answer(made, JSON.stringify({ question: "Shall I add a leap-year test too?" }), 2);
    const parked = step({ type: "parked", park: { reason: "person", unlock: "answer", retry_at: null } }, 3);
    const session = { status: "parked" as const, park: { reason: "person" as const, unlock: "answer", retry_at: null }, archived_at: null };
    const open = read([asked, asks, made, echoed, parked], { session });
    expect(only(open.entries, "ask")).toMatchObject({ question: "Shall I add a leap-year test too?", open: true });
    expect(open.status).toEqual({ text: "Needs you: answer the agent's question", needsYou: true, working: false });
    const replied = read([asked, asks, made, echoed, parked, said("Yes, please.")]);
    expect(only(replied.entries, "ask").open).toBe(false);
  });

  it("draws a park only a person clears as the agent's ask that holds its unlock, which no message answers", () => {
    const parked = step({ type: "parked", park: { reason: "person", unlock: "step_guard", retry_at: null } }, 3);
    const session = { status: "parked" as const, park: { reason: "person" as const, unlock: "step_guard", retry_at: null }, archived_at: null };
    const { entries, status } = read([...turn(), parked], { session });
    const ask = entries[entries.length - 1]!;
    expect(ask).toMatchObject({ kind: "ask", open: true, unlock: "step_guard", line: null });
    expect(answers(ask)).toBe(false);
    expect(status.needsYou).toBe(true);
    expect(status.text).not.toContain("answer");
  });

  it("draws a plan, a pull request, a validation, and a result as cards", () => {
    const asked = request(0);
    const asks = response(asked, 1, {
      tool_uses: [
        toolUse("p1", "write_plan", { plan: "1. Reproduce\n2. Fix the parser" }),
        toolUse("p2", "open_pull_request", { title: "Parse dates in UTC", body: "Fixes the failing test." }),
        toolUse("p3", "validate", {}),
        toolUse("p4", "submit_result", { claim: "succeeded", evidence: ["r1", "r2"] }),
      ],
    });
    const calls = ["p1", "p2", "p3", "p4"].map((id, index) => call(asks, id, asks.tool_uses[index]!.name, 2 + index));
    const answers = [
      JSON.stringify({ plan: "1. Reproduce\n2. Fix the parser" }),
      JSON.stringify({ id: "pr-1", url: "twin://ajax/first/pull/1", branch: "session/abc", head: "f00d" }),
      JSON.stringify({ validations: ["v1"], version: "0123456789abcdef", runs: ["r1", "r2"] }),
      "The result is accepted, verified: the loop ends succeeded.",
    ].map((text, index) => answer(calls[index]!, text, 6 + index));
    const { entries } = read([asked, asks, ...calls, ...answers]);
    expect(entries.map((entry) => (entry.kind === "card" ? `${entry.card}: ${entry.title} [${entry.facts.join("; ")}]` : entry.kind))).toEqual([
      "plan: Plan []",
      "pull_request: Parse dates in UTC [session/abc; twin://ajax/first/pull/1]",
      "validation: Validation [2 runs; at 0123456789ab]",
      "result: Result [claims succeeded; 2 records cited]",
    ]);
    expect(entries[0]!.kind === "card" && entries[0]!.body).toBe("1. Reproduce\n2. Fix the parser");
  });

  it("draws a hand-off as a sub-agent card that opens the session it started", () => {
    const asked = request(0);
    const asks = response(asked, 1, { tool_uses: [toolUse("h1", "hand_off_to_engineer", { title: "Fix the parser", objective: "Make the test pass" })] });
    const made = call(asks, "h1", "hand_off_to_engineer", 2);
    const done = answer(made, JSON.stringify({ session_id: "child-1", note: "started" }), 3);
    expect(only(read([asked, asks, made, done]).entries, "subagent")).toMatchObject({ title: "Fix the parser", agent: "engineer", childId: "child-1" });
  });

  it("draws a control, a park, a resume, and the loop's end as thin lines", () => {
    const { entries } = read([
      step({ type: "control", actor: "person", command: "pause" }, 0),
      step({ type: "parked", park: { reason: "resource", unlock: "workspace", retry_at: "2026-10-05T10:42:00Z" } }, 1),
      step({ type: "resumed" }, 2),
      step({ type: "control", actor: "person", command: "deny", text: "Leave the migrations alone" }, 3),
      step({ type: "loop_ended", outcome: "succeeded" }, 252),
    ]);
    expect(entries.map((entry) => (entry.kind === "line" ? entry.text : entry.kind))).toEqual([
      "A person paused it",
      expect.stringMatching(/^Waiting for a workspace · retries /),
      "Resumed",
      "A person denied a call: “Leave the migrations alone”",
      "Run ended: succeeded · 4m 12s",
    ]);
  });

  it("folds a summary, a switch, and an event into one line each", () => {
    const { entries } = read([step({ type: "summary", text: "Earlier: fixed the parser." }), step({ type: "switched" }), step({ type: "event", actor: "external", text: "CI passed" })]);
    expect(entries.map((entry) => (entry.kind === "fold" ? entry.label : entry.kind))).toEqual([
      "Summarized the history",
      "Switched to a new version of its agent",
      "An event arrived",
    ]);
  });

  it("streams a step not stored yet at the end, and drops the stream once its step lands", () => {
    const steps = turn().slice(0, 3);
    const live: LiveStream[] = [
      { stepId: "step-out", last: 3, dropped: false, runs: [{ kind: "tool_output", tool: "run_command", toolUseId: null, text: "collecting…\n" }] },
      {
        stepId: "step-next",
        last: 9,
        dropped: false,
        runs: [
          { kind: "thinking", tool: null, toolUseId: null, text: "Now the" },
          { kind: "text", tool: null, toolUseId: null, text: "The parser reads" },
        ],
      },
    ];
    const session = { status: "running" as const, park: null, archived_at: null };
    const streaming = read(steps, { live, session });
    expect(kinds(streaming.entries)).toEqual(["thought", "prose", "work", "prose"]);
    const work = only(streaming.entries, "work");
    expect(work.items.map((item) => item.kind)).toEqual(["call", "thought"]);
    expect(work.items[0]).toMatchObject({ body: "collecting…\n", call: { liveOutput: "collecting…\n" } });
    expect(work.items[1]).toMatchObject({ live: true, text: "Now the" });
    expect(streaming.entries[3]).toMatchObject({ kind: "prose", live: true, text: "The parser reads" });

    const landed = response(request(20), 21, { text: "The parser reads local time." });
    const settled = read([...steps, landed], { live: [{ ...live[1]!, stepId: landed.id }], session });
    expect(settled.entries.filter((entry) => entry.kind === "prose").map((entry) => entry.kind === "prose" && [entry.text, entry.live])).toEqual([
      ["I'll run the tests first.", false],
      ["The parser reads local time.", false],
    ]);
  });

  it("keeps a call's line when its content is gone, and its ask with it", () => {
    const asked = request(0);
    const gone = response(asked, 1, { tools: [] });
    const ran = call(gone, "u9", "run_command", 2);
    const { entries } = read([asked, gone, ran, answer(ran, "", 3)]);
    const work = only(entries, "work");
    expect(work.items[0]).toMatchObject({ gist: "Ran a command", call: { input: null, state: "done" } });
  });

  it("hands a tool the product draws to its card", () => {
    const asked = request(0);
    const asks = response(asked, 1, { tool_uses: [toolUse("s1", "run_on_rig", { rig: "r-1" })] });
    const made = call(asks, "s1", "run_on_rig", 2);
    const { entries } = read([asked, asks, made], { carded: new Set(["run_on_rig"]) });
    expect(only(entries, "product").line.call).toMatchObject({ tool: "run_on_rig", input: { rig: "r-1" }, state: "stopped" });
  });

  it("says Done when the last run succeeded, and how it ended otherwise", () => {
    expect(read([step({ type: "loop_ended", outcome: "succeeded" })]).status.text).toBe("Done");
    expect(read([step({ type: "loop_ended", outcome: "failed" })]).status.text).toMatch(/^Ended: failed/);
  });
});

describe("the platform's lines", () => {
  it("quotes a command's words only where a shell needs it", () => {
    expect(commandLine(["pytest", "-q", "tests/test dates.py", "it's"])).toBe("pytest -q 'tests/test dates.py' 'it'\\''s'");
  });

  it("reads each platform tool in words", () => {
    expect(PLATFORM_GISTS["read_file"]!({ path: "src/dates.py" }, "")).toBe("Read src/dates.py");
    expect(PLATFORM_GISTS["search_code"]!({ pattern: "parse(", path: "src" }, "")).toBe("Searched for “parse(” in src");
    expect(PLATFORM_GISTS["write_file"]!({ path: "a.txt", text: "x\ny\n" }, "")).toBe("Wrote a.txt +2 −0");
    expect(PLATFORM_GISTS["open_pull_request"]!({ title: "Parse dates in UTC" }, "")).toBe("Opened a pull request “Parse dates in UTC”");
  });

  it("reads a call that has not answered by what it asks: a held command has not run", () => {
    expect(PLATFORM_GISTS["run_command"]!({ argv: ["pytest", "-q"] }, null)).toBe("Run `pytest -q`");
    expect(PLATFORM_GISTS["run_command"]!({ argv: ["pytest", "-q"] }, '{"exit_code": 1}')).toBe("Ran `pytest -q` · exit 1");
    expect(PLATFORM_GISTS["validate"]!({}, null)).toBe("Validate the head");
  });

  it("says a duration the short way", () => {
    expect([duration(0.2), duration(4), duration(72), duration(7500)]).toEqual(["1s", "4s", "1m 12s", "2h 5m"]);
  });
});

describe("a call's body", () => {
  it("reads an answer with lines outside its hunks as a log, so every line is drawn", () => {
    const show = "commit 0123abc\nAuthor: A <a@example.test>\n\n    Tidy\n\ndiff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n";
    expect(bodyKindOf(show)).toBe("log");
    expect(bodyKindOf("Changed:\n@@ -1 +1 @@\n-old\n+new")).toBe("log");
    expect(bodyKindOf("--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new")).toBe("diff");
    expect(bodyKindOf('{"ok": true}')).toBe("json");
  });
});

describe("what the view cut short", () => {
  /** A 400-line file, as the API shows it: its first MAX_SHOWN characters and an ellipsis. */
  const whole = Array.from({ length: 400 }, (_, index) => `value_${index} = ${index}`).join("\n") + "\n";
  const shown = `${whole.slice(0, MAX_SHOWN)}…`;

  it("knows a string the view cut by its characters, as the API counts them", () => {
    expect(isCut("x".repeat(MAX_SHOWN))).toBe(false);
    expect(isCut(shown)).toBe(true);
    expect(isCut("😀".repeat(MAX_SHOWN))).toBe(false);
  });

  it("counts no lines of an edit or a write it cut, and marks its diff cut", () => {
    expect(PLATFORM_GISTS["write_file"]!({ path: "big.py", text: shown }, "")).toBe("Wrote big.py");
    expect(PLATFORM_GISTS["edit_file"]!({ path: "big.py", old_text: "a\n", new_text: shown }, "")).toBe("Edited big.py");
    const asked = request(0);
    const writes = response(asked, 1, { tool_uses: [toolUse("w1", "write_file", { path: "big.py", text: shown }), toolUse("w2", "write_file", { path: "small.py", text: "a\n" })] });
    const wrote = call(writes, "w1", "write_file", 2);
    const small = call(writes, "w2", "write_file", 3);
    const steps = [asked, writes, wrote, answer(wrote, "{}", 3), small, answer(small, "{}", 4)];
    const work = only(read(steps).entries, "work");
    expect(work.items.map((item) => item.kind === "call" && [item.gist, item.bodyKind, item.cut])).toEqual([
      ["Wrote big.py", "diff", true],
      ["Wrote small.py +1 −0", "diff", false],
    ]);
  });

  it("reads a plan from its answer, which keeps it whole, and marks a pull request's body cut", () => {
    const asked = request(0);
    const asks = response(asked, 1, {
      tool_uses: [toolUse("p1", "write_plan", { plan: shown }), toolUse("p2", "open_pull_request", { title: "Add values", body: shown })],
    });
    const planned = call(asks, "p1", "write_plan", 2);
    const opened = call(asks, "p2", "open_pull_request", 3);
    const steps = [asked, asks, planned, answer(planned, JSON.stringify({ plan: whole }), 3), opened, answer(opened, JSON.stringify({ id: "pr-1", url: "twin://ajax/first/pull/1", branch: "session/abc", head: "f00d" }), 4)];
    const cards = read(steps).entries.flatMap((entry) => (entry.kind === "card" ? [[entry.card, entry.body === whole, entry.cut]] : []));
    expect(cards).toEqual([
      ["plan", true, false],
      ["pull_request", false, true],
    ]);
    const unanswered = read([asked, asks, planned]).entries.find((entry) => entry.kind === "card");
    expect(unanswered).toMatchObject({ card: "plan", body: shown, cut: true });
  });
});

describe("the calls a product reads", () => {
  it("hands every call the entries hold, in order, a card's and a block's alike", () => {
    const steps = turn();
    const asked = request(10);
    const plans = response(asked, 11, { tool_uses: [toolUse("p1", "write_plan", { plan: "1. Fix it." })] });
    const made = call(plans, "p1", "write_plan", 12);
    const { entries } = read([...steps, asked, plans, made, answer(made, JSON.stringify({ plan: "1. Fix it." }), 12)]);
    expect(callsOf(entries).map((each) => [each.id, each.tool])).toEqual([
      ["u1", "run_command"],
      ["p1", "write_plan"],
    ]);
  });
});
