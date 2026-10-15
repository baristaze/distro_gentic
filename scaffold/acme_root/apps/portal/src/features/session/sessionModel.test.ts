import { describe, expect, it } from "vitest";
import type { agent_sessions, evidence } from "@acme/client";
import {
  allowed,
  composerOf,
  workProductLines,
  heldBy,
  parkLine,
  pullRequestBadge,
  runRow,
  splitCommand,
  statusLine,
  usageLine,
} from "./sessionModel";

const at = "2026-10-03T10:00:00Z";

const session: agent_sessions.AgentSessionView = {
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
  visibility: "private",
  participants: [],
  steerer: "u1",
};

describe("status and parks", () => {
  it("says archived first, and a parked session in the warning tone", () => {
    expect(statusLine({ status: "parked", archived_at: null })).toEqual({ label: "parked", tone: "danger" });
    expect(statusLine({ status: "idle", archived_at: at })).toEqual({ label: "archived", tone: "plain" });
  });

  it("says why a park waits, what clears it, and the action a person takes", () => {
    expect(parkLine({ reason: "person", unlock: "approval", retry_at: null, cause: null })).toMatchObject({ action: "decide", unlock: "a decision on the call it holds" });
    expect(parkLine({ reason: "person", unlock: "step_guard", retry_at: null, cause: null })).toMatchObject({ action: "unlock", unlock: "lifting its step guard" });
    expect(parkLine({ reason: "handover", unlock: "give_back", retry_at: null, cause: null }).action).toBe("give_back");
    expect(parkLine({ reason: "pause", unlock: "resume", retry_at: null, cause: null }).action).toBe("resume");
    expect(parkLine({ reason: "provider", unlock: "provider", retry_at: at, cause: null })).toMatchObject({ action: null, retryAt: at });
  });

});

describe("runs, work product, and usage", () => {
  it("says a run's check, outcome, cases, and a twin's provenance beside it", () => {
    const run: evidence.ExecutionView = {
      id: "r1",
      agent_step_id: "step-4",
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
      agent_project: "p",
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
      workProductLines({
        branch: "agent/tidy",
        branch_seen: true,
        agent_project_id: null,
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
    expect(Object.values(allowed({ ...session, status: "running" }, false, "u1")).some(Boolean)).toBe(false);
  });

  it("offers pause while it runs, resume while paused, and give back while a person has control, each with the cancel beside it", () => {
    expect(allowed({ ...session, status: "running" }, true, "u1")).toMatchObject({ pause: true, resume: false, cancel: true, archive: false });
    expect(allowed({ ...session, status: "pending" }, true, "u1")).toMatchObject({ pause: true, resume: false, cancel: true, archive: false });
    expect(allowed({ ...session, status: "parked", park: { reason: "pause", unlock: "resume", retry_at: null, cause: null } }, true, "u1")).toMatchObject({ resume: true, cancel: true, pause: false });
    expect(allowed({ ...session, status: "parked", park: { reason: "handover", unlock: "give_back", retry_at: null, cause: null } }, true, "u1")).toMatchObject({
      giveBack: true,
      cancel: true,
      takeControl: false,
      send: false,
    });
    expect(allowed({ ...session, status: "parked", park: { reason: "person", unlock: "approval", retry_at: null, cause: null } }, true, "u1")).toMatchObject({ cancel: true });
    expect(allowed(session, true, "u1")).toMatchObject({ archive: true, compact: true });
  });

  it("leaves a hand-over its holder names to them alone: another member ends the run, and never works in it or gives it back", () => {
    const held = (holder: string | null) => ({ ...session, status: "parked" as const, park: { reason: "handover" as const, unlock: "give_back", retry_at: null, cause: null, holder } });
    expect(heldBy(held("u1"), "u1")).toBeNull();
    expect(allowed(held("u1"), true, "u1")).toMatchObject({ giveBack: true, cancel: true });
    expect(heldBy(held("u2"), "u1")).toBe("u2");
    expect(allowed(held("u2"), true, "u1")).toMatchObject({ giveBack: false, cancel: true, takeControl: false, send: false });
    // A hand-over that names nobody, such as a person's push, is any writer's.
    expect(heldBy(held(null), "u1")).toBeNull();
    expect(allowed(held(null), true, "u1")).toMatchObject({ giveBack: true, cancel: true });
  });

  it("lets a person send at any time, running or not, until a person takes control", () => {
    const parked = (reason: "pause" | "handover", unlock: "resume" | "give_back") => ({ ...session, status: "parked" as const, park: { reason, unlock, retry_at: null, cause: null } });
    expect(allowed({ ...session, status: "running" }, true, "u1").send).toBe(true);
    expect(allowed({ ...session, status: "pending" }, true, "u1").send).toBe(true);
    expect(allowed(parked("pause", "resume"), true, "u1").send).toBe(true);
    expect(allowed(session, true, "u1").send).toBe(true);
    expect(allowed(parked("handover", "give_back"), true, "u1").send).toBe(false);
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
  it("turns the composer to an answer while the agent asks, and to a reply or a steer otherwise", () => {
    expect(composerOf(true, undefined)).toEqual({ label: "Answer", placeholder: "Answer the agent's question" });
    expect(composerOf(false, undefined).placeholder).toBe('Reply or steer, e.g. "Also add a test for leap years"');
    expect(composerOf(false, "e.g. Re-run it").placeholder).toBe("e.g. Re-run it");
  });

  it("badges the last pull request the session opened, by its number", () => {
    const pr = (handle: string) => ({ kind: "pull_request" as const, handle, bound_at: at });
    expect(pullRequestBadge({ work: [] })).toBeNull();
    expect(pullRequestBadge({ work: [pr("forge/acme/first#3"), pr("forge/acme/first#12")] })).toEqual({ label: "#12", handle: "forge/acme/first#12", more: 1 });
    expect(pullRequestBadge({ work: [pr("draft")] })?.label).toBe("draft");
  });
});
