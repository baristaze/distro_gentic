import { describe, expect, it } from "vitest";
import type { AutomationView } from "@acme/client";
import { actionLine, automationRequest, automationRow, draftOf, EMPTY_DRAFT, everyLine, limitsLine, principalRoles, secondsOf, spanLine, type AutomationDraft } from "./automationsModel";

const SESSION = "0b8e5d2a-1c3f-4e6a-9b7d-2f4c6e8a0b1c";
const draft = (fields: Partial<AutomationDraft>): AutomationDraft => ({
  ...EMPTY_DRAFT,
  name: "Nightly tidy",
  agentKind: "assistant",
  title: "Tidy the docs",
  brief: "Tidy the **docs**.",
  costCap: "2",
  runCap: "0.5",
  ...fields,
});

const saved: AutomationView = {
  id: "a1",
  name: "Triage",
  trigger: { kind: "event", integrations: ["forge"], arrivals: ["comment"], effects: [], every: null },
  action: { kind: "message_session", brief: "Look.", agent_kind: null, title: null, project_id: null, session_id: SESSION, params: {} },
  limits: { cost_cap_micros: 3_000_000, run_cap_micros: 1_000_000, period: "PT1H", rate: 5, concurrency: 2, queue: true, queue_depth: 7, hop_limit: 2 },
  runs_as: "automation_principal",
  own_events: true,
  enabled: false,
  created_at: "",
  created_by: "u1",
  updated_at: "",
  updated_by: "u1",
};

describe("durations", () => {
  it("reads an ISO 8601 span, and nothing else", () => {
    expect(secondsOf("PT1H")).toBe(3_600);
    expect(secondsOf("P1D")).toBe(86_400);
    expect(secondsOf("PT1M30S")).toBe(90);
    expect(secondsOf("P1W")).toBe(604_800);
    for (const text of ["", "P", "PT", "1H", "PT1X"]) expect(secondsOf(text)).toBeNull();
  });
  it("says a span in words", () => {
    expect(spanLine(86_400)).toBe("1 day");
    expect(spanLine(9_000)).toBe("2 hours 30 minutes");
    expect(everyLine("P1D")).toBe("every day");
    expect(everyLine("PT7200S")).toBe("every 2 hours");
    expect(limitsLine(saved.limits)).toBe("3.00 an hour (1.00 a run), 5 firings an hour, 2 at once, a queue of 7");
  });
});

describe("automationRequest", () => {
  it("makes a schedule that starts a session", () => {
    expect(automationRequest(draft({ projectId: "p1" }))).toEqual({
      request: {
        name: "Nightly tidy",
        trigger: { kind: "schedule", every: "PT86400S", integrations: [], arrivals: [], effects: [] },
        action: { kind: "start_session", brief: "Tidy the **docs**.", agent_kind: "assistant", title: "Tidy the docs", project_id: "p1", session_id: null },
        limits: { cost_cap_micros: 2_000_000, run_cap_micros: 500_000, period: "P1D", rate: 10, concurrency: 1, queue: false, queue_depth: 50, hop_limit: 3 },
        runs_as: "creator",
        enabled: true,
        own_events: false,
      },
    });
  });
  it("makes an event trigger from its filters, split on commas", () => {
    const made = automationRequest(draft({ triggerKind: "event", integrations: " forge, ,chat ", arrivals: "comment" }));
    expect("request" in made && made.request.trigger).toEqual({ kind: "event", every: null, integrations: ["forge", "chat"], arrivals: ["comment"], effects: [] });
  });
  it("refuses what the API refuses, saying why", () => {
    const problem = (fields: Partial<AutomationDraft>, projectRequired = false) => {
      const made = automationRequest(draft(fields), { projectRequired });
      return "problem" in made ? made.problem : null;
    };
    expect(problem({ name: " " })).toBe("Give the automation a name.");
    expect(problem({ every: "0" })).toBe("Say how often the schedule fires, as a whole number.");
    expect(problem({ every: "1.5" })).toBe("Say how often the schedule fires, as a whole number.");
    expect(problem({ brief: "" })).toBe("Write the brief the session is given.");
    expect(problem({ agentKind: "" })).toBe("Name the kind of session it starts.");
    expect(problem({ title: "" })).toBe("Give the sessions it starts a title.");
    expect(problem({}, true)).toBe("Choose the project its sessions work in.");
    expect(problem({ actionKind: "message_session", sessionId: "not-an-id" })).toBe("Name the standing session by its id.");
    expect(problem({ costCap: "0" })).toBe("Set the most its runs spend in a period, as an amount above zero.");
    expect(problem({ runCap: "abc" })).toBe("Set the most one run spends, as an amount above zero.");
    expect(problem({ runCap: "3" })).toBe("One run's cap is within the automation's.");
    expect(problem({ rate: "-1" })).toBe("Set the most firings in a period, as a whole number above zero.");
    expect(problem({ concurrency: "" })).toBe("Set the most runs at work at once, as a whole number above zero.");
  });
  it("edits a saved automation and keeps what the form does not show", () => {
    const made = automationRequest(draftOf(saved) ?? EMPTY_DRAFT, { kept: saved });
    expect(made).toEqual({
      request: {
        name: "Triage",
        trigger: { kind: "event", every: null, integrations: ["forge"], arrivals: ["comment"], effects: [] },
        action: { kind: "message_session", brief: "Look.", agent_kind: null, title: null, project_id: null, session_id: SESSION },
        limits: { cost_cap_micros: 3_000_000, run_cap_micros: 1_000_000, period: "PT1H", rate: 5, concurrency: 2, queue: true, queue_depth: 7, hop_limit: 2 },
        runs_as: "automation_principal",
        enabled: false,
        own_events: true,
      },
    });
  });
});

it("shows a row in words", () => {
  expect(automationRow(saved, [])).toEqual({
    id: "a1",
    name: "Triage",
    trigger: "on an event from forge, arriving as comment",
    action: `message the session ${SESSION}`,
    runsAs: "the automation principal",
    enabled: false,
  });
});

it("shows a product's own action by its kind, and offers no form to edit it", () => {
  const product: AutomationView = { ...saved, action: { kind: "run_job", brief: null, agent_kind: null, title: null, project_id: null, session_id: null, params: { steps: 2 } } };
  expect(actionLine(product.action, [])).toBe("run the product's action run_job");
  expect(draftOf(product)).toBeNull();
});

it("offers the principal no role above the granter's own", () => {
  expect(principalRoles("owner")).toEqual(["admin", "member", "viewer"]);
  expect(principalRoles("member")).toEqual(["member", "viewer"]);
  expect(principalRoles(undefined)).toEqual([]);
});
