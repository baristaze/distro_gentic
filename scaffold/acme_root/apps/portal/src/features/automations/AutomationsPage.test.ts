// @vitest-environment jsdom
// The automations list and one automation's page over a fake transport that
// answers as the API does: each org reads its own automations, and one
// another org holds answers 404. A member who may not write is offered no
// form; one who does not manage the org is offered no grant.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AutomationView } from "@acme/client";
import { buttons, container, enter, mount, newNet, notFound, PEOPLE, press, unmount, writes, type Call } from "../screenTesting";
import { AutomationPage } from "./AutomationPage";
import { AutomationsPage } from "./AutomationsPage";

const net = vi.hoisted(() => ({}) as ReturnType<typeof newNet>);
vi.mock("../../app/api", async () => (await import("../screenTesting")).fakeApi(net));
vi.mock("../../app/AppNav", () => ({ AppNav: () => null }));
vi.mock("../../app/config", () => ({ runtimeConfig: () => ({ environment: "local" }) }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const automation = (org: "a" | "b", name: string): AutomationView => ({
  id: `au${org}`,
  name,
  trigger: { kind: "schedule", every: "P1D", integrations: [], arrivals: [], effects: [] },
  action: { kind: "start_session", brief: "Tidy the **docs**.", agent_kind: "assistant", title: "Tidy", project_id: null, session_id: null },
  limits: { cost_cap_micros: 2_000_000, run_cap_micros: 500_000, period: "P1D", rate: 10, concurrency: 1, queue: false, queue_depth: 50, hop_limit: 3 },
  runs_as: "creator",
  own_events: false,
  enabled: true,
  created_at: "2026-10-03T10:00:00Z",
  created_by: PEOPLE[org].id,
  updated_at: "2026-10-03T10:00:00Z",
  updated_by: PEOPLE[org].id,
});
const HELD = { a: automation("a", "Ajax nightly"), b: automation("b", "Beta nightly") };

function answer(call: Call): unknown {
  const held = HELD[net.org];
  if (call.method === "GET" && call.path.startsWith("/v1/automations?")) return [held];
  if (call.method === "GET" && call.path.startsWith("/v1/projects?")) return [];
  if (call.method === "GET" && call.path === "/v1/automations/principal") return notFound(call.path);
  if (call.method === "PUT" && call.path === "/v1/automations/principal") {
    return { id: "pr1", role: (call.body as { role: string }).role, granted_by: PEOPLE[net.org].id, created_at: "2026-10-03T10:00:00Z" };
  }
  if (call.path === `/v1/automations/${held.id}`) return call.method === "PUT" ? { ...held, ...(call.body as object) } : held;
  if (call.method === "POST" && call.path === "/v1/automations") return { ...held, id: "aunew" };
  return notFound(call.path);
}

const routes = [
  { path: "/automations", Component: AutomationsPage },
  { path: "/automations/:automationId", Component: AutomationPage },
];

beforeEach(() => Object.assign(net, newNet(), { answer }));
afterEach(unmount);

describe("the automations list", () => {
  it("shows the org's own automations and none of another's", async () => {
    await mount(routes, "/automations");
    expect(container.querySelector("table[aria-label='Automations']")!.textContent).toContain("Ajax nightly");
    expect(container.textContent).toContain("every day");
    expect(container.textContent).not.toContain("Beta nightly");
    expect(container.querySelector("[data-principal]")!.textContent).toBe("No role is granted to the principal yet.");
  });

  it("makes an automation from the form", async () => {
    await mount(routes, "/automations");
    await enter("Name", "Nightly tidy");
    await enter("Session kind", "assistant");
    await enter("Session title", "Tidy the docs");
    await enter("Brief", "Tidy the docs.");
    await enter("Cost cap a period", "2");
    await enter("Cost cap a run", "0.5");
    await press("Make the automation");
    const [made] = writes(net);
    expect(made).toMatchObject({ method: "POST", path: "/v1/automations" });
    expect(made!.body).toMatchObject({
      name: "Nightly tidy",
      trigger: { kind: "schedule", every: "PT86400S" },
      action: { kind: "start_session", agent_kind: "assistant", title: "Tidy the docs", brief: "Tidy the docs." },
      limits: { cost_cap_micros: 2_000_000, run_cap_micros: 500_000 },
    });
  });

  it("says why a form is refused, and sends nothing", async () => {
    await mount(routes, "/automations");
    await enter("Name", "Nightly tidy");
    await press("Make the automation");
    expect(container.querySelector("[role='alert']")!.textContent).toBe("Write the brief the session is given.");
    expect(writes(net)).toEqual([]);
  });

  it("grants the principal a role no higher than the granter's", async () => {
    net.role = "admin";
    await mount(routes, "/automations");
    await enter("Role", "member");
    await press("Grant");
    expect(writes(net)).toEqual([{ method: "PUT", path: "/v1/automations/principal", body: { role: "member" } }]);
    expect(container.querySelector("[data-principal]")!.textContent).toMatch(/^The principal holds the role member, granted by Ada/);
  });

  it("offers a viewer no form and no grant, and a member no grant", async () => {
    net.role = "viewer";
    await mount(routes, "/automations");
    expect(container.querySelectorAll("form")).toHaveLength(0);
    await unmount();
    net.role = "member";
    await mount(routes, "/automations");
    expect(container.querySelector("form[aria-label='New automation']")).not.toBeNull();
    expect(container.querySelector("form[aria-label='Grant the principal']")).toBeNull();
  });
});

describe("an automation's page", () => {
  it("shows nothing of an automation another org holds", async () => {
    await mount(routes, "/automations/aub");
    expect(container.querySelector("h1")!.textContent).toBe("No automation here");
    expect(container.textContent).not.toContain("Beta nightly");
  });

  it("edits the automation and keeps what the form does not show", async () => {
    await mount(routes, "/automations/aua");
    expect(container.querySelector("[data-automation]")!.textContent).toContain("start a session of the kind assistant");
    await press("Edit the automation");
    await enter("Name", "Ajax nightly, renamed");
    await press("Save");
    expect(writes(net)).toEqual([
      {
        method: "PUT",
        path: "/v1/automations/aua",
        body: expect.objectContaining({ name: "Ajax nightly, renamed", own_events: false, limits: expect.objectContaining({ queue_depth: 50, hop_limit: 3 }) }),
      },
    ]);
  });

  it("offers a viewer no edit", async () => {
    net.role = "viewer";
    await mount(routes, "/automations/aua");
    expect(buttons()).not.toContain("Edit the automation");
  });
});
