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
import { keys } from "../../queries/keys";
import { SessionPage } from "./SessionPage";

const net = vi.hoisted(() => ({
  org: "a" as "a" | "b",
  calls: [] as string[],
  history: null as unknown[] | null,
  environment: "local",
  projects: [] as { id: string; name: string }[],
  posts: [] as { path: string; body: unknown }[],
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
  const held = HELD[net.org];
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

async function open(org: "a" | "b", address: string, history: StepView[] | null = null) {
  net.org = org;
  net.calls = [];
  net.history = history;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/sessions", Component: SessionsPage },
      { path: "/sessions/:sessionId", Component: SessionPage },
    ],
    { initialEntries: [address] },
  );
  root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client: queryClient }, createElement(RouterProvider, { router }))));
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
  Object.assign(net, { environment: "local", projects: [], posts: [] });
});

describe("a second org's session", () => {
  it("is not in the list: the list shows only the sessions the route returns for the member's org", async () => {
    await open("b", "/sessions");
    const titles = [...container.querySelectorAll("tbody tr td:first-child")].map((cell) => cell.textContent);
    expect(titles).toEqual(["Beta's own session"]);
    expect(container.textContent).not.toContain("Ajax's own session");
  });

  it("shows nothing of it at its address, and nothing past the refused read is asked for", async () => {
    await open("b", "/sessions/sa?tab=timeline");
    expect(container.querySelector("h1")!.textContent).toBe("No session here");
    expect(container.textContent).not.toContain("Ajax");
    expect(net.calls.filter((path) => path.startsWith("/v1/agent-sessions/"))).toEqual(["/v1/agent-sessions/sa"]);
  });
});

describe("the org's own session", () => {
  it("draws its thread from the history", async () => {
    await open("a", "/sessions/sa");
    expect(container.querySelector("h1")!.textContent).toBe("Ajax's own session");
    const said = [...container.querySelectorAll("[aria-label='Messages'] li")].map((item) => item.getAttribute("data-who"));
    expect(said).toEqual(["person", "agent"]);
    expect(container.querySelector("[aria-label='Messages'] strong")!.textContent).toBe("docs");
  });

  it("draws its timeline, every step in order", async () => {
    await open("a", "/sessions/sa?tab=timeline");
    const steps = [...container.querySelectorAll("[aria-label='Steps'] [data-title]")].map((title) => title.textContent);
    expect(steps).toEqual(["Message from a person", "Model answered", "Loop ended: succeeded"]);
  });

  it("draws a 3,000-step timeline's lines and only the bodies opened", async () => {
    const long = Array.from({ length: 3000 }, (_, index) =>
      step(index + 1, { type: "tool_response", actor: "program", tool: "run", text: `output of step ${index + 1}` }),
    );
    const queryClient = await open("a", "/sessions/sa?tab=timeline", long);
    const steps = container.querySelector("[aria-label='Steps']")!;
    expect(steps.querySelectorAll("li")).toHaveLength(3000);
    expect(steps.querySelectorAll(".acme-timeline-body")).toHaveLength(0);
    expect(net.calls.filter((path) => path.includes("/steps?"))).toHaveLength(15);
    const show = [...steps.querySelectorAll("li")][41]!.querySelector("button")!;
    expect(show.textContent).toBe("Show");
    await act(async () => show.click());
    const bodies = [...steps.querySelectorAll(".acme-timeline-body")];
    expect(bodies).toHaveLength(1);
    expect(bodies[0]!.textContent).toContain("output of step 42");

    // A push for the session reads only the steps past the last one held.
    long.push(step(3001, { type: "loop_ended", outcome: "succeeded" }));
    net.calls = [];
    await act(async () => queryClient.invalidateQueries({ queryKey: keys.agentSessions.one("sa") }));
    await settle();
    expect(net.calls.filter((path) => path.includes("/steps?"))).toEqual(["/v1/agent-sessions/sa/steps?after_seq=3000&limit=200"]);
    expect(steps.querySelectorAll("li")).toHaveLength(3001);
  });

  it("draws its evidence: each run with its outcome and a twin's provenance", async () => {
    await open("a", "/sessions/sa?tab=evidence");
    const cells = [...container.querySelectorAll("table[aria-label='Runs'] tbody td")].map((cell) => cell.textContent);
    expect(cells.slice(0, 5)).toEqual(["unit 1", "work", "passed", "twin, never reported as real", "4 passed"]);
    expect(container.textContent).toContain("1 model call: 10 tokens in, 5 out");
  });
});
