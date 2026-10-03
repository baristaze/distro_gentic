import { describe, expect, it } from "vitest";
import type { AgentSessionView } from "@acme/client";
import { sessionRow, startRequest, statusFilter, TITLE_MAX } from "./sessionsModel";

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
    expect(startRequest({ title: " Tidy ", kind: " assistant " })).toEqual({ request: { title: "Tidy", kind: "assistant" } });
    expect(startRequest({ title: "", kind: "assistant" })).toEqual({ problem: "Give the session a title." });
    expect(startRequest({ title: "x".repeat(TITLE_MAX + 1), kind: "assistant" })).toEqual({ problem: "A title is at most 200 characters." });
    expect(startRequest({ title: "Tidy", kind: " " })).toEqual({ problem: "Name the kind of work it does." });
  });
});
