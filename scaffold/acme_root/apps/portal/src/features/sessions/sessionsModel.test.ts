import { describe, expect, it } from "vitest";
import type { AgentSessionView } from "@acme/client";
import {
  listed,
  listFilterParams,
  NO_PROJECT,
  projectChoice,
  projectRequired,
  readListFilter,
  serverStatus,
  sessionRow,
  startRequest,
  statusFilter,
  TITLE_MAX,
} from "./sessionsModel";

const session: AgentSessionView = {
  id: "s1",
  root_id: "s0",
  parent_id: "s0",
  kind: "assistant",
  kind_version: 1,
  title: "  ",
  status: "running",
  park: null,
  created_at: "2026-10-03T10:00:00Z",
  created_by: "u1",
  archived_at: null,
  deleted_at: null,
};

describe("sessions model", () => {
  it("shows a session with no title as Untitled, with its status and the session that started it", () => {
    expect(sessionRow(session)).toMatchObject({ title: "Untitled", status: "running", tone: "accent", parentId: "s0" });
  });

  it("reads a status filter from the address bar, and anything else as every status", () => {
    expect([statusFilter("parked"), statusFilter("needs_you"), statusFilter("bogus"), statusFilter(null)]).toEqual([
      "parked",
      "needs_you",
      "any",
      "any",
    ]);
    expect([serverStatus("any"), serverStatus("needs_you"), serverStatus("idle")]).toEqual([null, "parked", "idle"]);
  });

  it("keeps the whole filter in the address bar, and only what narrows the list", () => {
    const filter = readListFilter(new URLSearchParams("needs=you&owner=mine&agent=analysis&archived=1&q=flaky"));
    expect(filter).toEqual({ status: "needs_you", owner: "mine", kind: "analysis", archived: true, query: "flaky" });
    expect(listFilterParams(filter)).toEqual({ status: "needs_you", owner: "mine", agent: "analysis", archived: "1", q: "flaky" });
    expect(listFilterParams(readListFilter(new URLSearchParams("owner=all")))).toEqual({});
  });

  it("narrows the sessions read to whose they are, the agent, the archived, the title's words, and those that need a person", () => {
    const one = (id: string, over: Partial<AgentSessionView>): AgentSessionView => ({ ...session, id, title: id, ...over });
    const sessions = [
      one("Flaky test", { created_by: "u1", kind: "engineer" }),
      one("Docs", { created_by: "u2", kind: "analysis" }),
      one("Old", { created_by: "u1", archived_at: "2026-10-04T00:00:00Z" }),
      one("Asks", { status: "parked", park: { reason: "person", unlock: "approval", retry_at: null } }),
      one("Waits", { status: "parked", park: { reason: "provider", unlock: "provider", retry_at: null } }),
    ];
    const ids = (filter: Partial<Parameters<typeof listed>[1]>) =>
      listed(sessions, { status: "any", owner: "everyone", kind: "", archived: false, query: "", ...filter }, "u1").map((each) => each.id);
    expect(ids({})).toEqual(["Flaky test", "Docs", "Asks", "Waits"]);
    expect(ids({ owner: "mine" })).toEqual(["Flaky test", "Asks", "Waits"]);
    expect(ids({ kind: "analysis" })).toEqual(["Docs"]);
    expect(ids({ archived: true })).toContain("Old");
    expect(ids({ query: "FLAKY" })).toEqual(["Flaky test"]);
    expect(ids({ status: "needs_you" })).toEqual(["Asks"]);
  });

  it("starts a session only with a title and a kind, trimmed", () => {
    const local = { required: false, count: 0 };
    expect(startRequest({ title: " Tidy ", kind: " assistant ", projectId: "" }, local)).toEqual({ request: { title: "Tidy", kind: "assistant" } });
    expect(startRequest({ title: "", kind: "assistant", projectId: "" }, local)).toEqual({ problem: "Give the session a title." });
    expect(startRequest({ title: "x".repeat(TITLE_MAX + 1), kind: "assistant", projectId: "" }, local)).toEqual({
      problem: "A title is at most 200 characters.",
    });
    expect(startRequest({ title: "Tidy", kind: " ", projectId: "" }, local)).toEqual({ problem: "Name the kind of work it does." });
  });

  it("sends the chosen project, and says why it cannot start when a project is required and there is none", () => {
    const draft = { title: "Tidy", kind: "assistant", projectId: "p1" };
    expect(startRequest(draft, { required: true, count: 1 })).toEqual({ request: { title: "Tidy", kind: "assistant", project_id: "p1" } });
    expect(startRequest(draft, { required: false, count: 1 })).toEqual({ request: { title: "Tidy", kind: "assistant", project_id: "p1" } });
    expect(startRequest({ ...draft, projectId: "" }, { required: true, count: 2 })).toEqual({ problem: "Choose the project it works in." });
    expect(startRequest({ ...draft, projectId: "" }, { required: true, count: 0 })).toEqual({ problem: NO_PROJECT });
  });

  it("offers the org's projects, a choice of one outside the local stack, and says so when there is none", () => {
    const projects = [{ id: "p1", name: "Docs" }];
    expect(projectChoice(projects, true)).toEqual({
      options: [
        { value: "", label: "Choose a project" },
        { value: "p1", label: "Docs" },
      ],
      problem: null,
    });
    expect(projectChoice([], true)).toEqual({ options: [], problem: NO_PROJECT });
    expect(projectChoice([], false)).toEqual({ options: [{ value: "", label: "No project" }], problem: null });
    expect(projectChoice(null, true)).toEqual({ options: [], problem: null });
    expect([projectRequired("local"), projectRequired("staging"), projectRequired("production")]).toEqual([false, true, true]);
  });
});
