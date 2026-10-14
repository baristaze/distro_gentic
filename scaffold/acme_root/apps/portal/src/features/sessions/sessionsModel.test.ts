import { describe, expect, it } from "vitest";
import type { AgentSessionView } from "@acme/client";
import { standingOf } from "../session/sessionModel";
import {
  amongOf,
  listed,
  listFilterParams,
  NO_AGENT_PROJECT,
  agentProjectChoice,
  agentProjectRequired,
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
  visibility: "private",
  participants: [],
  steerer: "u1",
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
    const filter = readListFilter(new URLSearchParams("view=org&needs=you&agent=analysis&archived=1&q=flaky"));
    expect(filter).toEqual({ view: "org", status: "needs_you", kind: "analysis", archived: true, query: "flaky" });
    expect(listFilterParams(filter)).toEqual({ view: "org", status: "needs_you", agent: "analysis", archived: "1", q: "flaky" });
    expect(listFilterParams(readListFilter(new URLSearchParams("view=all&owner=mine")))).toEqual({});
  });

  it("asks for the person's own first, and for every session they see in the org's view", () => {
    expect(readListFilter(new URLSearchParams("")).view).toBe("mine");
    expect([amongOf("mine"), amongOf("org")]).toEqual(["mine", "visible"]);
  });

  it("keeps a private session out of the org's view, though the server listed it, as it does for one who may audit", () => {
    const one = (id: string, over: Partial<AgentSessionView>): AgentSessionView => ({ ...session, id, title: id, parent_id: null, ...over });
    const read = [
      one("Mine, private", { created_by: "u1", visibility: "private" }),
      one("Mine, org-wide", { created_by: "u1", visibility: "org_wide" }),
      one("Theirs, org-wide", { created_by: "u2", visibility: "org_wide" }),
      one("Theirs, private", { created_by: "u2", visibility: "private" }),
      one("Joined, private", { created_by: "u2", visibility: "private", participants: ["u1"] }),
    ];
    const ids = (view: "mine" | "org") => listed(read, { view, status: "any", kind: "", archived: false, query: "" }).map((each) => each.id);
    expect(ids("org")).toEqual(["Mine, org-wide", "Theirs, org-wide"]);
    expect(ids("mine")).toEqual(read.map((each) => each.id));
    expect(read.map((each) => standingOf(each, "u1"))).toEqual(["made", "made", "none", "none", "joined"]);
    expect(sessionRow(read[2]!, "u1")).toMatchObject({ createdBy: "u2", visibility: "org_wide", standing: "none" });
  });

  it("narrows the sessions read to the agent, the archived, the title's words, and those that need a person", () => {
    const one = (id: string, over: Partial<AgentSessionView>): AgentSessionView => ({ ...session, id, title: id, ...over });
    const sessions = [
      one("Flaky test", { created_by: "u1", kind: "software_engineer" }),
      one("Docs", { created_by: "u2", kind: "analysis" }),
      one("Old", { created_by: "u1", archived_at: "2026-10-04T00:00:00Z" }),
      one("Asks", { status: "parked", park: { reason: "person", unlock: "approval", retry_at: null, cause: null } }),
      one("Waits", { status: "parked", park: { reason: "provider", unlock: "provider", retry_at: null, cause: null } }),
    ];
    const ids = (filter: Partial<Parameters<typeof listed>[1]>) =>
      listed(sessions, { view: "mine", status: "any", kind: "", archived: false, query: "", ...filter }).map((each) => each.id);
    expect(ids({})).toEqual(["Flaky test", "Docs", "Asks", "Waits"]);
    expect(ids({ kind: "analysis" })).toEqual(["Docs"]);
    expect(ids({ archived: true })).toContain("Old");
    expect(ids({ query: "FLAKY" })).toEqual(["Flaky test"]);
    expect(ids({ status: "needs_you" })).toEqual(["Asks"]);
  });

  it("leaves support conversations out, and shows them under the platform assistant's filter", () => {
    const one = (id: string, over: Partial<AgentSessionView>): AgentSessionView => ({ ...session, id, ...over });
    const sessions = [
      one("work", { title: "Fix the flaky test", kind: "software_engineer" }),
      one("support", { title: "Support", kind: "platform_assistant", created_by: "u1" }),
      one("theirs", { title: "Support", kind: "platform_assistant", created_by: "u2" }),
      one("composed", { title: "Draft the webhook settings", kind: "platform_assistant" }),
    ];
    const ids = (kind: string) =>
      listed(sessions, { view: "mine", status: "any", kind, archived: false, query: "" }).map((each) => each.id);
    expect(ids("")).toEqual(["work", "composed"]);
    expect(ids("platform_assistant")).toEqual(["support", "theirs", "composed"]);
  });

  it("starts a session only with a title and a kind, trimmed", () => {
    const local = { required: false, count: 0 };
    expect(startRequest({ title: " Tidy ", kind: " assistant ", agentProjectId: "" }, local)).toEqual({ request: { title: "Tidy", kind: "assistant" } });
    expect(startRequest({ title: "", kind: "assistant", agentProjectId: "" }, local)).toEqual({ problem: "Give the session a title." });
    expect(startRequest({ title: "x".repeat(TITLE_MAX + 1), kind: "assistant", agentProjectId: "" }, local)).toEqual({
      problem: "A title is at most 200 characters.",
    });
    expect(startRequest({ title: "Tidy", kind: " ", agentProjectId: "" }, local)).toEqual({ problem: "Name the kind of work it does." });
  });

  it("sends the chosen agent project, and says why it cannot start when an agent project is required and there is none", () => {
    const draft = { title: "Tidy", kind: "assistant", agentProjectId: "p1" };
    expect(startRequest(draft, { required: true, count: 1 })).toEqual({ request: { title: "Tidy", kind: "assistant", agent_project_id: "p1" } });
    expect(startRequest(draft, { required: false, count: 1 })).toEqual({ request: { title: "Tidy", kind: "assistant", agent_project_id: "p1" } });
    expect(startRequest({ ...draft, agentProjectId: "" }, { required: true, count: 2 })).toEqual({ problem: "Choose the agent project it works in." });
    expect(startRequest({ ...draft, agentProjectId: "" }, { required: true, count: 0 })).toEqual({ problem: NO_AGENT_PROJECT });
  });

  it("offers the org's agent projects, a choice of one outside the local stack, and says so when there is none", () => {
    const agentProjects = [{ id: "p1", name: "Docs" }];
    expect(agentProjectChoice(agentProjects, true)).toEqual({
      options: [
        { value: "", label: "Choose an agent project" },
        { value: "p1", label: "Docs" },
      ],
      problem: null,
    });
    expect(agentProjectChoice([], true)).toEqual({ options: [], problem: NO_AGENT_PROJECT });
    expect(agentProjectChoice([], false)).toEqual({ options: [{ value: "", label: "No agent project" }], problem: null });
    expect(agentProjectChoice(null, true)).toEqual({ options: [], problem: null });
    expect([agentProjectRequired("local"), agentProjectRequired("staging"), agentProjectRequired("production")]).toEqual([false, true, true]);
  });
});
