import { describe, expect, it } from "vitest";
import type { AgentSessionView } from "@acme/client";
import { NO_PROJECT, projectChoice, projectRequired, sessionRow, startRequest, statusFilter, TITLE_MAX } from "./sessionsModel";

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
    expect([statusFilter("parked"), statusFilter("bogus"), statusFilter(null)]).toEqual(["parked", "any", "any"]);
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
