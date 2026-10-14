// @vitest-environment jsdom
// Sessions and a session's page over a fake transport that holds the org's
// sessions and answers as the API does: a person's own list holds the ones
// they made or take part in; the sessions they see are the org-wide ones and
// their own, or every one for a role that may reassign sessions; a member
// joins an org-wide one, and a private one's creator adds who takes part;
// only the steerer hands the steer on, to one who takes part; and a message
// from one who does not steer is a participant's.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, type AgentSessionView, type MeView, type StepView } from "@acme/client";
import { PLATFORM } from "../../app/platform";
import { SlotProvider } from "../../app/slot";
import { usePanesStore } from "../../store/panes";
import { SessionPage } from "../session/SessionPage";
import { SessionsPage } from "./SessionsPage";

const at = "2026-10-12T10:00:00Z";

const server = vi.hoisted(() => ({
  me: "u1",
  sessions: [] as AgentSessionView[],
  steps: {} as Record<string, StepView[]>,
  writes: [] as { method: string; path: string; body?: unknown }[],
}));

const PEOPLE = [
  { id: "u1", display_name: "Ada", email: "ada@a.test", created_at: at },
  { id: "u2", display_name: "Bea", email: "bea@a.test", created_at: at },
  { id: "u3", display_name: "Cy", email: "cy@a.test", created_at: at },
];
/** Cy is an admin, who may reassign sessions and sees every one for an audit. */
const ROLES: Record<string, { role: string; permissions: string[] }> = {
  u1: { role: "member", permissions: ["read", "write"] },
  u2: { role: "member", permissions: ["read", "write"] },
  u3: { role: "admin", permissions: ["read", "write", "manage_members", "manage_sessions"] },
};

function sessionOf(id: string, by: string, visibility: AgentSessionView["visibility"], participants: string[] = []): AgentSessionView {
  return {
    id,
    root_id: id,
    parent_id: null,
    kind: "software_engineer",
    kind_version: 1,
    title: id,
    status: "idle",
    park: null,
    created_at: at,
    created_by: by,
    archived_at: null,
    deleted_at: null,
    visibility,
    participants,
    steerer: by,
  };
}

function stepOf(seq: number, fields: Partial<StepView>): StepView {
  return {
    id: `st${seq}`,
    seq,
    loop_id: "l1",
    type: "message",
    actor: "person",
    origin: "portal",
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
    snapshot: null,
    stop_reason: null,
    tool: null,
    tools: [],
    usage: null,
    cause: null,
    author: null,
    participant: false,
    steerer: null,
    visibility: null,
    ...fields,
  };
}

const takesPart = (session: AgentSessionView, person: string) => session.created_by === person || session.participants.includes(person);
const sees = (session: AgentSessionView, person: string) =>
  takesPart(session, person) || session.visibility === "org_wide" || ROLES[person]!.permissions.includes("manage_sessions");
const refused = (status: number, path: string) => new ApiError(status, status === 404 ? "not_found" : "forbidden", `refused ${path}`, "req-1");

function read(path: string): unknown {
  const [bare = "", query = ""] = path.split("?");
  const me = server.me;
  if (bare === "/v1/me") return { app: "portal", role: ROLES[me]!.role, permissions: ROLES[me]!.permissions, user: PEOPLE.find((one) => one.id === me), org: { id: "o1" } } as unknown as MeView;
  if (bare === "/v1/users") return { items: PEOPLE, next_cursor: null };
  if (bare === "/v1/memberships") return { items: PEOPLE.map((one) => ({ id: `m-${one.id}`, user_id: one.id, role: ROLES[one.id]!.role, teams: [] })), next_cursor: null };
  if (bare === "/v1/agent-sessions") {
    const params = new URLSearchParams(query);
    const mine = params.get("among") === "mine";
    const items = server.sessions.filter((session) => (mine ? takesPart(session, me) : sees(session, me)) && (params.get("status") === null || session.status === params.get("status")));
    return { items, next_cursor: null };
  }
  const [, , , id, part] = bare.split("/").map(decodeURIComponent);
  const session = server.sessions.find((one) => one.id === id);
  if (!session || !sees(session, me)) throw refused(404, path);
  if (!part) return session;
  if (part === "steps") return { has_more: false, items: (server.steps[session.id] ?? []).filter((one) => one.seq > Number(new URLSearchParams(query).get("after_seq"))) };
  if (part === "work-product") return { branch: null, branch_seen: false, project_id: null, report: null, work: [] };
  if (part === "children" || part === "executions") return { items: [], next_cursor: null };
  if (part === "tool-calls") return { has_more: false, items: [] };
  if (part === "approvals" || part === "validations") return [];
  throw refused(404, path);
}

/** The writes, under the API's rules for who may make each. */
function write(method: string, path: string, body?: unknown): unknown {
  server.writes.push(body === undefined ? { method, path } : { method, path, body });
  const me = server.me;
  const [, , , id, part, target] = path.split("/").map(decodeURIComponent);
  const index = server.sessions.findIndex((one) => one.id === id);
  const session = server.sessions[index];
  if (!session || !sees(session, me)) throw refused(404, path);
  const steps = (server.steps[session.id] ??= []);
  if (method === "PUT" && part === "participants") {
    // A self-join takes an org-wide session, or a private one its joiner
    // steers; anyone else's add is its creator's alone.
    const selfJoin = target === me && (session.visibility === "org_wide" || session.steerer === me);
    if (session.created_by !== me && !selfJoin) throw refused(403, path);
    const joined = session.participants.includes(target!) ? session : { ...session, participants: [...session.participants, target!] };
    server.sessions[index] = joined;
    return joined;
  }
  if (method === "PUT" && part === "principal") {
    const to = (body as { steerer?: string } | undefined)?.steerer ?? me;
    if (session.steerer !== me) throw refused(403, path);
    if (!takesPart(session, to)) throw refused(422, path);
    const moved = { ...session, steerer: to };
    server.sessions[index] = moved;
    steps.push(stepOf(steps.length + 1, { type: "switched", actor: "person", steerer: to }));
    return moved;
  }
  if (method === "POST" && part === "messages") {
    if (!takesPart(session, me) && session.steerer !== me) throw refused(403, path);
    const said = stepOf(steps.length + 1, { text: (body as { text: string }).text, author: me, participant: session.steerer !== me });
    steps.push(said);
    return said;
  }
  throw refused(404, path);
}

vi.mock("../../app/api", () => {
  const answer = (run: () => unknown) => {
    try {
      return Promise.resolve(run());
    } catch (caught) {
      return Promise.reject(caught);
    }
  };
  return {
    api: {
      get: (path: string) => answer(() => read(path)),
      post: (path: string, body?: unknown) => answer(() => write("POST", path, body)),
      request: (method: string, path: string, body?: unknown) => answer(() => write(method, path, body)),
    },
  };
});
vi.mock("../../app/config", () => ({ runtimeConfig: () => ({ environment: "local" }) }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const container = document.createElement("div");
document.body.append(container);
let root: ReturnType<typeof createRoot> | null = null;

/** The reads settle over a few turns of the event loop. */
async function settle() {
  for (let turn = 0; turn < 6; turn += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
}

async function open(person: string, address: string) {
  await act(async () => root?.unmount());
  server.me = person;
  const router = createMemoryRouter(
    [
      { path: "/sessions", Component: SessionsPage },
      { path: "/sessions/:sessionId", Component: SessionPage },
    ],
    { initialEntries: [address] },
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  const app = createElement(SlotProvider, { slot: PLATFORM, children: createElement(RouterProvider, { router }) });
  await act(async () => root!.render(createElement(QueryClientProvider, { client: queryClient }, app)));
  await settle();
  return router;
}

const q = <T extends Element = HTMLElement>(selector: string) => container.querySelector<T>(selector);
const titles = () => [...container.querySelectorAll("tbody tr td:first-child")].map((cell) => cell.textContent);
const buttonOf = (words: string, within: ParentNode = container) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === words);
async function click(button: HTMLElement | undefined) {
  if (!button) throw new Error("no such button");
  await act(async () => button.click());
  await settle();
}

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  usePanesStore.setState({ panes: {} });
  localStorage.clear();
  Object.assign(server, { me: "u1", sessions: [], steps: {}, writes: [] });
});

describe("Sessions", () => {
  const seed = () => {
    server.sessions = [
      sessionOf("Ada's draft", "u1", "private"),
      sessionOf("Ada's release", "u1", "org_wide"),
      sessionOf("Bea's flaky test", "u2", "org_wide"),
      sessionOf("Bea's private notes", "u2", "private"),
      sessionOf("Bea's audit", "u2", "private", ["u1"]),
    ];
  };

  it("lists the person's own first, and the org's view the org-wide ones, never another person's private one", async () => {
    seed();
    await open("u1", "/sessions");
    expect(q("h1")!.textContent).toBe("Sessions");
    expect(titles()).toEqual(["Ada's draft", "Ada's release", "Bea's audit"]);
    expect(q("table")!.getAttribute("aria-label")).toBe("Your sessions");
    await click(buttonOf("The org's"));
    expect(titles()).toEqual(["Ada's release", "Bea's flaky test"]);
    expect(container.textContent).not.toContain("Bea's private notes");
  });

  it("keeps another person's private session out of the org's view for one who may see it for an audit", async () => {
    seed();
    await open("u3", "/sessions?view=org");
    expect(titles()).toEqual(["Ada's release", "Bea's flaky test"]);
    expect(container.textContent).not.toContain("Ada's draft");
    expect(container.textContent).not.toContain("Bea's private notes");
  });

  it("offers an admin no Join on another member's private session, and Join on an org-wide one", async () => {
    seed();
    await open("u3", `/sessions/${encodeURIComponent("Bea's private notes")}`);
    expect(container.textContent).not.toContain("Join this session");
    expect(container.textContent).not.toContain("Join");
    await open("u3", `/sessions/${encodeURIComponent("Bea's flaky test")}`);
    expect(container.textContent).toContain("Join this session to take part");
  });

  it("joins a session of the org's: the person takes part, and it is on their own list", async () => {
    seed();
    await open("u1", "/sessions?view=org");
    const row = [...container.querySelectorAll("tbody tr")].find((each) => each.textContent?.includes("Bea's flaky test"))!;
    expect(row.textContent).toContain("Bea");
    expect([...container.querySelectorAll("tbody tr")].find((each) => each.textContent?.includes("Ada's release"))!.textContent).toContain("Yours");
    await click(buttonOf("Join", row));
    expect(server.writes).toEqual([{ method: "PUT", path: "/v1/agent-sessions/Bea's%20flaky%20test/participants/u1" }]);
    expect(server.sessions.find((one) => one.id === "Bea's flaky test")!.participants).toEqual(["u1"]);
    expect([...container.querySelectorAll("tbody tr")].find((each) => each.textContent?.includes("Bea's flaky test"))!.textContent).toContain("Joined");
    await click(buttonOf("Yours"));
    expect(titles()).toContain("Bea's flaky test");
  });
});

describe("a session's steerer", () => {
  const seed = () => {
    server.sessions = [sessionOf("s1", "u1", "org_wide", ["u2"])];
    server.steps = {
      s1: [
        stepOf(1, { text: "Fix the date parser.", author: "u1" }),
        // Its creator made it org-wide: a switch of who sees it, recorded as a step.
        stepOf(2, { type: "switched", visibility: "org_wide" }),
        stepOf(3, { text: "Try the leap-year case first.", author: "u2", participant: true }),
      ],
    };
  };
  const bubbles = () => [...container.querySelectorAll(".acme-bubble")];
  const chip = () => q<HTMLButtonElement>(".acme-sharing-chip")!;

  const switches = () => [...container.querySelectorAll("[data-kind='shared']")].map((row) => row.querySelector("span")!.textContent);

  it("marks a participant's message as a suggestion, and moves the steer on the steerer's hand-off, which the page then shows", async () => {
    seed();
    await open("u1", "/sessions/s1");
    expect(bubbles().map((bubble) => [bubble.hasAttribute("data-suggestion"), bubble.querySelector(".acme-bubble-by")?.textContent ?? null])).toEqual([
      [false, null],
      [true, "Suggestion from Bea"],
    ]);
    expect(chip().textContent).toBe("You steer");
    expect(switches()).toEqual(["Made org-wide: every member of the org sees it and may join"]);

    await click(chip());
    const hand = [...container.querySelectorAll("select")].find((select) => document.getElementById(select.getAttribute("aria-labelledby")!)?.textContent === "Hand the steer to")!;
    expect([...hand.options].map((option) => option.textContent)).toEqual(["Choose who takes part", "Bea"]);
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(hand, "u2");
      hand.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await click(buttonOf("Hand it over"));

    expect(server.writes).toEqual([{ method: "PUT", path: "/v1/agent-sessions/s1/principal", body: { steerer: "u2" } }]);
    expect(chip().textContent).toBe("Bea steers");
    // Each switch says what it was, never a new version of its agent.
    expect(switches()).toEqual(["Made org-wide: every member of the org sees it and may join", "Bea steers it from here"]);
    expect(container.textContent).not.toContain("Switched to a new version of its agent");
    // Ada takes part still, and her message is a suggestion now.
    expect(q("textarea")!.getAttribute("placeholder")).toBe("Suggest something to Bea, who steers it");
  });

  it("shows the steerer to everyone: the new steerer, and a member who has not joined, who is offered Join", async () => {
    seed();
    server.sessions[0] = { ...server.sessions[0]!, steerer: "u2" };
    await open("u2", "/sessions/s1");
    expect(chip().textContent).toBe("You steer");
    expect(q("textarea")!.getAttribute("placeholder")).not.toContain("Suggest");

    await open("u3", "/sessions/s1");
    expect(chip().textContent).toBe("Bea steers");
    expect(q("textarea")).toBeNull();
    expect(q(".acme-composer-join")!.textContent).toContain("Join this session to take part. Bea steers it");
    await click(buttonOf("Join", q(".acme-composer-join")!));
    expect(server.writes).toEqual([{ method: "PUT", path: "/v1/agent-sessions/s1/participants/u3" }]);
    expect(q("textarea")!.getAttribute("placeholder")).toBe("Suggest something to Bea, who steers it");
  });
});
