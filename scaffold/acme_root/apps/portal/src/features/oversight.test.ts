// @vitest-environment jsdom
// The org's approvals, audit, and usage, and the banner a page shows while
// the org's sessions wait on a model provider, over a fake transport that
// answers as the API does: each org reads its own, and nothing of
// another's reaches its screens.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentSessionView, ApprovalView, BudgetUsageView, EventView } from "@acme/client";
import { ApprovalsPage } from "./approvals/ApprovalsPage";
import { AuditPage } from "./audit/AuditPage";
import { buttons, container, mount, newNet, notFound, PEOPLE, press, unmount, type Call } from "./screenTesting";
import { UsagePage } from "./usage/UsagePage";

const net = vi.hoisted(() => ({}) as ReturnType<typeof newNet>);
vi.mock("../app/api", async () => (await import("./screenTesting")).fakeApi(net));
vi.mock("../app/AppNav", () => ({ AppNav: () => null }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const at = "2026-10-03T10:00:00Z";
const APPROVALS: Record<"a" | "b", ApprovalView[]> = {
  a: [{ session_id: "sa", seq: 3, requested_at: at, tool: "ajax_push", authorization_class: "write", principal_id: PEOPLE.a.id }],
  b: [{ session_id: "sb", seq: 5, requested_at: at, tool: "beta_push", authorization_class: "write", principal_id: PEOPLE.b.id }],
};
const EVENTS: Record<"a" | "b", EventView[]> = {
  a: [{ seq: 1, kind: "projects.project.created", target_id: "pa", produced_at: at, actor_id: PEOPLE.a.id }],
  b: [{ seq: 1, kind: "knowledge.entry.created", target_id: "kb", produced_at: at, actor_id: PEOPLE.b.id }],
};
const usage = (org: "a" | "b", spent: number): BudgetUsageView => ({
  budget: { id: `b${org}`, scope_kind: "person", scope_key: PEOPLE[org].id, window_kind: "day", window_seconds: null, cost_micros: 10_000_000, tokens: null, version: 1 },
  window_start: at,
  spent_cost_micros: spent,
  held_cost_micros: 0,
  spent_tokens: 0,
  held_tokens: 0,
});
const USAGE = { a: [usage("a", 2_500_000)], b: [usage("b", 9_000_000)] };

function answer(call: Call): unknown {
  if (call.path.startsWith("/v1/approvals?")) return { items: APPROVALS[net.org], next_cursor: null };
  if (call.path.startsWith("/v1/events/recent?")) return EVENTS[net.org];
  if (call.path.startsWith("/v1/usage?")) return { items: USAGE[net.org], next_cursor: null };
  if (call.path.startsWith("/v1/projects?")) return [];
  return notFound(call.path);
}

const routes = [
  { path: "/approvals", Component: ApprovalsPage },
  { path: "/audit", Component: AuditPage },
  { path: "/usage", Component: UsagePage },
];

beforeEach(() => Object.assign(net, newNet(), { answer }));
afterEach(unmount);

describe.each(["a", "b"] as const)("a member of org %s", (org) => {
  const other = org === "a" ? "b" : "a";
  beforeEach(() => {
    net.org = org;
    net.role = "viewer";
  });

  it("sees the org's own held calls, each linked to its session", async () => {
    await mount(routes, "/approvals");
    const table = container.querySelector("table[aria-label='Approvals']")!;
    expect(table.textContent).toContain(APPROVALS[org][0]!.tool);
    expect(table.textContent).toContain(PEOPLE[org].display_name);
    expect(table.querySelector("a")!.getAttribute("href")).toBe(`/sessions/s${org}`);
    expect(container.textContent).not.toContain(APPROVALS[other][0]!.tool);
  });

  it("sees the org's own events, by whom", async () => {
    await mount(routes, "/audit");
    const table = container.querySelector("table[aria-label='Events']")!;
    expect(table.textContent).toContain(PEOPLE[org].display_name);
    expect(table.textContent).not.toContain(PEOPLE[other].display_name);
    expect(table.textContent).toContain(org === "a" ? "project created" : "entry created");
  });

  it("sees the org's own budgets", async () => {
    await mount(routes, "/usage");
    const table = container.querySelector("table[aria-label='Budgets']")!;
    expect(table.textContent).toContain(PEOPLE[org].display_name);
    expect(table.textContent).toContain(org === "a" ? "2.50 spent, of 10.00" : "9.00 spent, of 10.00");
    expect(table.textContent).not.toContain(PEOPLE[other].display_name);
  });
});

describe("the org's records, past one page and past a trim", () => {
  it("shows a held call that only a later page of parked sessions holds", async () => {
    net.answer = (call) => {
      if (call.path.startsWith("/v1/approvals?")) {
        return call.path.includes("cursor=p2") ? { items: APPROVALS.a, next_cursor: null } : { items: [], next_cursor: "p2" };
      }
      return answer(call);
    };
    await mount(routes, "/approvals");
    const table = container.querySelector("table[aria-label='Approvals']")!;
    expect(table.textContent).toContain(APPROVALS.a[0]!.tool);
    expect(container.textContent).not.toContain("No call waits on a person.");
  });

  it("opens the audit on the newest events and pages older ones back to the floor", async () => {
    // Kept: 71 to 250, the floor at 70. Each read answers the newest below `before_seq`.
    const event = (seq: number): EventView => ({ seq, kind: "projects.project.updated", target_id: `p${seq}`, produced_at: at, actor_id: PEOPLE.a.id });
    net.answer = (call) => {
      if (call.path.startsWith("/v1/events/recent?")) {
        const query = new URLSearchParams(call.path.split("?")[1]);
        const top = Math.min(Number(query.get("before_seq") ?? 251) - 1, 250);
        const bottom = Math.max(top - Number(query.get("limit")), 70);
        return Array.from({ length: Math.max(top - bottom, 0) }, (_, at) => event(top - at));
      }
      return answer(call);
    };
    await mount(routes, "/audit");
    const seqs = () => [...container.querySelectorAll("table[aria-label='Events'] tbody tr")].map((row) => Number(row.querySelector("td")!.textContent));
    expect(seqs().slice(0, 2)).toEqual([250, 249]);
    expect(seqs()).toHaveLength(100);
    await press("Load older");
    expect(net.calls.map((call) => call.path).filter((path) => path.startsWith("/v1/events"))).toEqual([
      "/v1/events/recent?limit=100",
      "/v1/events/recent?limit=100&before_seq=151",
    ]);
    expect(seqs()).toHaveLength(180);
    expect(seqs().at(-1)).toBe(71);
    expect(buttons()).not.toContain("Load older");
  });

  it("credits the automation principal with what its runs did", async () => {
    const principal = { id: "pr1", role: "member", granted_by: PEOPLE.a.id, created_at: at };
    net.answer = (call) => {
      if (call.path === "/v1/automations/principal") return principal;
      if (call.path.startsWith("/v1/events/recent?")) return [{ ...EVENTS.a[0]!, actor_id: principal.id }];
      if (call.path.startsWith("/v1/approvals?")) return { items: [{ ...APPROVALS.a[0]!, principal_id: principal.id }], next_cursor: null };
      return answer(call);
    };
    await mount(routes, "/audit");
    expect(container.querySelector("table[aria-label='Events']")!.textContent).toContain("the automation principal");
    expect(container.textContent).not.toContain("a former member");
    await unmount();
    await mount(routes, "/approvals");
    expect(container.querySelector("table[aria-label='Approvals']")!.textContent).toContain("the automation principal");
  });
});

describe("the provider banner", () => {
  const parked = (unlock: string, retry_at: string | null): AgentSessionView =>
    ({ id: "s1", park: { reason: "provider", unlock, retry_at }, status: "parked" }) as unknown as AgentSessionView;

  it("says nothing while no session waits on a provider", async () => {
    await mount(routes, "/usage");
    expect(container.querySelector("[data-outage]")).toBeNull();
  });

  it("says the provider is out, and when the sessions try again", async () => {
    net.parked = [parked("anthropic", "2026-10-03T10:05:00Z")];
    await mount(routes, "/usage");
    expect(container.querySelector("[data-outage='out']")!.textContent).toMatch(/^Anthropic is not answering\. 1 session waits, and tries again by itself from /);
  });

  it("sends a missing key to where one is saved", async () => {
    net.parked = [parked("openai:key", null)];
    await mount(routes, "/audit");
    const notice = container.querySelector("[data-outage='key']")!;
    expect(notice.textContent).toContain("1 session waits for the org's own key to OpenAI");
    expect(notice.querySelector("a")!.getAttribute("href")).toBe("/models");
  });
});
