// @vitest-environment jsdom
// All sessions and a session's page over a fake transport that answers
// as the API does: each org's member reads its own org's sessions, and a
// session another org holds answers 404. The page shows only what the routes
// return for the member's org, and asks for nothing of a session it was
// refused.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type AgentSessionView, type ExecutionView, type MeView, type StepView } from "@acme/client";
import { SessionsPage } from "../sessions/SessionsPage";
import { PLATFORM } from "../../app/platform";
import { SlotProvider } from "../../app/slot";
import { keys } from "../../queries/keys";
import { usePanesStore } from "../../store/panes";
import { SessionPage } from "./SessionPage";

const net = vi.hoisted(() => ({
  org: "a" as "a" | "b",
  calls: [] as string[],
  history: null as unknown[] | null,
  environment: "local",
  projects: [] as { id: string; name: string }[],
  posts: [] as { path: string; body: unknown }[],
  /** What the session's record says past the fixture's: its status, its park. */
  over: {} as Partial<AgentSessionView>,
  held: [] as unknown[],
}));

const at = "2026-10-03T10:00:00Z";
const sessionOf = (id: string, title: string): AgentSessionView => ({
  id,
  root_id: id,
  parent_id: null,
  kind: "assistant",
  kind_version: 1,
  title,
  status: "idle",
  park: null,
  created_at: at,
  created_by: "u1",
  archived_at: null,
  deleted_at: null,
});
const HELD = { a: sessionOf("sa", "Ajax's own session"), b: sessionOf("sb", "Beta's own session") };

const step = (seq: number, fields: Partial<StepView>): StepView => ({
  id: `st${seq}`,
  seq,
  loop_id: "l1",
  type: "event",
  actor: "engine",
  origin: "engine",
  text: "",
  thinking: "",
  tool_uses: [],
  tool_use_id: null,
  agent: null,
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
  usage: null,
  ...fields,
});

const RUN: ExecutionView = {
  id: "r1",
  step_id: "st3",
  validation_id: null,
  purpose: "work",
  check: "unit",
  check_version: "1",
  version: "abcdef0123456789",
  dirty: false,
  executor: "e",
  image: "img",
  host: "h1",
  isolation: "container",
  project: "p",
  provenance: "twin",
  outcome: "passed",
  cases: { passed: 4, failed: 0, skipped: 0 },
  started_at: at,
  finished_at: "2026-10-03T10:00:02Z",
  abort: null,
};

function answer(path: string): unknown {
  const held = { ...HELD[net.org], ...net.over };
  if (path === "/v1/me") return { app: "portal", role: "owner", permissions: ["read", "write"], user: { id: "u1" }, org: { id: net.org } } as unknown as MeView;
  if (path.startsWith("/v1/agent-sessions?")) return { items: [held], next_cursor: null };
  if (path.startsWith("/v1/projects?")) return net.projects;
  const [, , , id, part] = path.split("?")[0]!.split("/");
  if (id !== held.id) throw new ApiError(404, "not_found", "session not found", "req-1");
  if (!part) return held;
  if (part === "steps" && net.history) {
    const query = new URLSearchParams(path.split("?")[1]);
    const after = Number(query.get("after_seq"));
    const limit = Number(query.get("limit"));
    const rest = (net.history as StepView[]).filter((each) => each.seq > after);
    return { has_more: rest.length > limit, items: rest.slice(0, limit) };
  }
  if (part === "steps")
    return {
      has_more: false,
      items: [
        step(1, { type: "message", actor: "person", origin: "portal", text: "Tidy the **docs**." }),
        step(2, { type: "model_response", actor: "model", text: "Done: the docs read well.", stop_reason: "end_turn" }),
        step(3, { type: "loop_ended", outcome: "succeeded" }),
      ],
    };
  if (part === "delivery")
    return { branch: "fix-dates", branch_seen: true, project_id: null, report: null, work: [{ kind: "pull_request", handle: "forge/acme/first#7", bound_at: at }] };
  if (part === "approvals") return net.held;
  if (part === "tool-calls") return { has_more: false, items: [] };
  if (part === "executions") return { items: [RUN], next_cursor: null };
  if (part === "validations") return [];
  if (part === "usage") return { calls: 1, input: 10, output: 5, thinking: 0, cache_read: 0, cache_write: 0, fills: [] };
  if (part === "bounds") return { kind: "assistant", kind_version: 1, kind_deadline_seconds: null, loop: { step_guard: 50, error_streak: 3, nudges: 1, run_time_seconds: 900 }, tree: { root_id: id, height: 2, count: 4, size: 0, concurrency: null, deadline: null } };
  throw new Error(`no read for ${path}`);
}

vi.mock("../../app/api", () => ({
  api: {
    get: (path: string) => {
      net.calls.push(path);
      try {
        return Promise.resolve(answer(path));
      } catch (caught) {
        return Promise.reject(caught);
      }
    },
    post: (path: string, body?: unknown) => {
      net.posts.push({ path, body });
      return path === "/v1/agent-sessions" ? Promise.resolve(HELD[net.org]) : Promise.reject(new Error(`no answer for ${path}`));
    },
  },
}));
vi.mock("../../app/config", () => ({ runtimeConfig: () => ({ environment: net.environment }) }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const container = document.createElement("div");
document.body.append(container);
let root: ReturnType<typeof createRoot> | null = null;
let router: ReturnType<typeof createMemoryRouter> | null = null;

async function open(org: "a" | "b", address: string, history: StepView[] | null = null) {
  net.org = org;
  net.calls = [];
  net.history = history;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  router = createMemoryRouter(
    [
      { path: "/sessions", Component: SessionsPage },
      { path: "/sessions/:sessionId", Component: SessionPage },
    ],
    { initialEntries: [address] },
  );
  root = createRoot(container);
  const page = createElement(SlotProvider, { slot: PLATFORM, children: createElement(RouterProvider, { router: router! }) });
  await act(async () => root!.render(createElement(QueryClientProvider, { client: queryClient }, page)));
  await settle();
  return queryClient;
}

/** The reads settle over a few turns of the event loop. */
async function settle() {
  for (let turn = 0; turn < 5; turn += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
}

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  usePanesStore.setState({ panes: {} });
  localStorage.clear();
  Object.assign(net, { environment: "local", projects: [], posts: [], over: {}, held: [] });
});

describe("a second org's session", () => {
  it("is not in the list: the list shows only the sessions the route returns for the member's org", async () => {
    await open("b", "/sessions");
    const titles = [...container.querySelectorAll("tbody tr td:first-child")].map((cell) => cell.textContent);
    expect(titles).toEqual(["Beta's own session"]);
    expect(container.textContent).not.toContain("Ajax's own session");
  });

  it("shows nothing of it at its address, and nothing past the refused read is asked for", async () => {
    await open("b", "/sessions/sa?pane=evidence");
    expect(container.querySelector("h1")!.textContent).toBe("No session here");
    expect(container.textContent).not.toContain("Ajax");
    expect(net.calls.filter((path) => path.startsWith("/v1/agent-sessions/"))).toEqual(["/v1/agent-sessions/sa"]);
  });
});

describe("the org's own session", () => {
  const rows = () => [...container.querySelectorAll("[aria-label='Timeline'] > li[data-kind]")];

  it("draws its history as a chat, the pull request it opened in its header, and its status last", async () => {
    await open("a", "/sessions/sa");
    expect(container.querySelector("h1")!.textContent).toBe("Ajax's own session");
    expect(rows().map((row) => row.getAttribute("data-kind"))).toEqual(["person", "prose", "line"]);
    expect(container.querySelector(".acme-bubble strong")!.textContent).toBe("docs");
    expect(container.querySelector(".acme-pr-badge")!.textContent).toBe("#7");
    expect(container.querySelector("[aria-label='Timeline'] [role='status']")!.textContent).toBe("Done");
    expect(container.querySelector("textarea")!.getAttribute("placeholder")).toBe('Reply or steer, e.g. "Also add a test for leap years"');
  });

  it("folds a 3,000-step history into one work block, and draws a call's answer only once its chevron opens it", async () => {
    const long: StepView[] = [];
    for (let n = 1; n <= 1000; n += 1) {
      const asked = step(long.length + 1, { type: "model_response", actor: "model", tool_uses: [{ id: `u${n}`, name: "run_command", input: { argv: ["make", `t${n}`] } }] });
      const made = step(long.length + 2, { type: "tool_request", actor: "agent", refs: [asked.id], tool: "run_command", tool_use_id: `u${n}` });
      const said = step(long.length + 3, { type: "tool_response", actor: "program", responds_to: made.id, tool: "run_command", tool_use_id: `u${n}`, text: `output of call ${n}` });
      long.push(asked, made, said);
    }
    const queryClient = await open("a", "/sessions/sa", long);
    expect(net.calls.filter((path) => path.includes("/steps?"))).toHaveLength(15);
    expect(rows().map((row) => row.getAttribute("data-kind"))).toEqual(["work"]);
    const block = rows()[0]!.querySelector<HTMLButtonElement>(".acme-fold-line")!;
    expect(block.textContent).toContain("1000 steps");
    expect(container.querySelectorAll(".acme-call")).toHaveLength(0);
    await act(async () => block.click());
    const calls = [...container.querySelectorAll(".acme-call")];
    expect(calls).toHaveLength(1000);
    expect(container.querySelectorAll(".acme-call-body")).toHaveLength(0);
    expect(calls[41]!.querySelector(".acme-call-line")!.textContent).toContain("make t42");
    await act(async () => calls[41]!.querySelector<HTMLButtonElement>(".acme-call-fold")!.click());
    const bodies = [...container.querySelectorAll(".acme-call-body")];
    expect(bodies).toHaveLength(1);
    expect(bodies[0]!.textContent).toContain("output of call 42");

    // A push for the session reads only the steps past the last one held.
    long.push(step(3001, { type: "loop_ended", outcome: "succeeded" }));
    net.calls = [];
    await act(async () => queryClient.invalidateQueries({ queryKey: keys.agentSessions.one("sa") }));
    await settle();
    expect(net.calls.filter((path) => path.includes("/steps?"))).toEqual(["/v1/agent-sessions/sa/steps?after_seq=3000&limit=200"]);
    expect(rows().map((row) => row.getAttribute("data-kind"))).toEqual(["work", "line"]);
  });

  it("draws a held call as an action card whose Approve sends the decision on that call", async () => {
    net.over = { status: "parked", park: { reason: "person", unlock: "approval", retry_at: null } };
    net.held = [{ seq: 3, session_id: "sa", tool: "run_command", authorization_class: "execute", principal_id: "u1", requested_at: at }];
    await open("a", "/sessions/sa", [
      step(1, { type: "message", actor: "person", origin: "portal", text: "Run the tests." }),
      step(2, { type: "model_response", actor: "model", tool_uses: [{ id: "u1", name: "run_command", input: { argv: ["pytest", "-q"] } }] }),
      step(3, { type: "tool_request", actor: "agent", refs: ["st2"], tool: "run_command", tool_use_id: "u1" }),
    ]);
    const card = container.querySelector("[aria-label='Action required']")!;
    expect(card.textContent).toContain("pytest -q");
    expect(card.textContent).toContain("execute");
    expect(container.querySelector("[aria-label='Timeline'] [role='status']")!.textContent).toBe("Needs you: approve run_command");
    const approve = [...card.querySelectorAll("button")].find((button) => button.textContent === "Approve")!;
    await act(async () => approve.click());
    expect(net.posts).toContainEqual({ path: "/v1/agent-sessions/sa/calls/3/decision", body: { approve: true } });
  });

  const pane = () => container.querySelector("[aria-label='Session pane']");
  const tabNames = () => [...container.querySelectorAll("[role='tab']")].map((tab) => tab.textContent);
  const address = () => router!.state.location.search;

  it("draws its evidence in the pane's tab the address names: each run with its outcome and a twin's provenance", async () => {
    await open("a", "/sessions/sa?pane=evidence");
    expect(tabNames()).toEqual(["Evidence"]);
    const cells = [...container.querySelectorAll("table[aria-label='Runs'] tbody td")].map((cell) => cell.textContent);
    expect(cells.slice(0, 5)).toEqual(["unit 1", "work", "passed", "twin, never reported as real", "4 passed"]);
    expect(net.calls.some((path) => path.includes("/usage"))).toBe(false);
  });

  it("opens a call's step in the pane from its line, and puts the step in the address", async () => {
    await open("a", "/sessions/sa", [
      step(1, { type: "model_response", actor: "model", tool_uses: [{ id: "u1", name: "run_command", input: { argv: ["pytest", "-q"] } }] }),
      step(2, { type: "tool_request", actor: "agent", refs: ["st1"], tool: "run_command", tool_use_id: "u1" }),
      step(3, { type: "tool_response", actor: "program", responds_to: "st2", tool: "run_command", tool_use_id: "u1", text: '{"stdout": "3 passed\\n", "exit_code": 0}' }),
    ]);
    expect(pane()).toBeNull();
    await act(async () => container.querySelector<HTMLButtonElement>(".acme-work .acme-fold-line")!.click());
    await act(async () => container.querySelector<HTMLButtonElement>(".acme-call-line")!.click());
    await settle();
    expect(tabNames()).toEqual(["Step"]);
    const shown = container.querySelector("[aria-label='Step']")!;
    expect(shown.textContent).toContain("run_command");
    expect(shown.textContent).toContain("3 passed");
    expect(shown.textContent).toContain("None needed");
    expect(new URLSearchParams(address()).get("pane")).toBe("step");
    expect(new URLSearchParams(address()).get("call")).toBe("u1");
    // "+" offers the rest; Plan is not among them, since it wrote none.
    await act(async () => container.querySelector<HTMLButtonElement>("button[aria-label='Open a view']")!.click());
    const offered = [...document.querySelectorAll("[role='menuitem']")].map((item) => item.textContent);
    expect(offered).toEqual(["Workspace", "Changes", "Evidence", "Sub-agents", "Usage"]);
    await act(async () => (document.querySelector("[role='menuitem']") as HTMLButtonElement).click());
    expect(tabNames()).toEqual(["Step", "Workspace"]);
    expect(new URLSearchParams(address()).get("pane")).toBe("workspace");
  });

  it("keeps Send open while the session runs, with Pause beside it", async () => {
    net.over = { status: "running" };
    await open("a", "/sessions/sa");
    const composer = container.querySelector<HTMLFormElement>("form[aria-label='Send a message']")!;
    const field = composer.querySelector<HTMLTextAreaElement>("textarea")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(field, "Use the fixture in conftest.py");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const send = composer.querySelector<HTMLButtonElement>("button[aria-label='Send']")!;
    expect(send.disabled).toBe(false);
    expect([...composer.querySelectorAll("button")].map((button) => button.textContent || button.getAttribute("aria-label"))).toEqual(["Pause", "Send"]);
  });

  it("says a person has control in place of Send while they hold it", async () => {
    net.over = { status: "parked", park: { reason: "handover", unlock: "give_back", retry_at: null } };
    await open("a", "/sessions/sa");
    expect(container.querySelector("form[aria-label='Send a message']")).toBeNull();
    expect(container.querySelector(".acme-session-composer")!.textContent).toBe("A person has control: the agent reads what they did once they give it back.");
  });

  it("opens Workspace by itself once while it runs; closed, it stays closed", async () => {
    net.over = { status: "running" };
    await open("a", "/sessions/sa");
    expect(tabNames()).toEqual(["Workspace"]);
    expect(pane()!.textContent).toContain("Take control");
    await act(async () => container.querySelector<HTMLButtonElement>("button[aria-label='Close Workspace']")!.click());
    expect(pane()).toBeNull();
    expect(new URLSearchParams(address()).get("pane")).toBeNull();
    await act(async () => root?.unmount());
    // A new visit to the same session keeps it closed.
    await open("a", "/sessions/sa");
    expect(pane()).toBeNull();
  });
});
