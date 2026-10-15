// @vitest-environment jsdom
// The agent projects list and an agent project's page over a fake transport that answers
// as the API does: each org's member reads its own org's agent projects, and an
// agent project another org holds answers 404. A member who does not manage the
// org is offered no form. The read credential's password goes out once, in
// the write, and is never on the page after it: not in a field, not in the
// text.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { agent_projects } from "@acme/client";
import { buttons, container, enter, field, mount, newNet, notFound, PEOPLE, press, unmount, writes, type Call } from "../screenTesting";
import { AgentProjectPage } from "./AgentProjectPage";
import { AgentProjectsPage } from "./AgentProjectsPage";

const net = vi.hoisted(() => ({}) as ReturnType<typeof newNet>);
vi.mock("../../app/api", async () => (await import("../screenTesting")).fakeApi(net));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const SECRET = "ghp_never-on-a-screen-1234";

const agentProject = (org: "a" | "b", name: string): agent_projects.AgentProjectView => ({
  id: `p${org}`,
  name,
  repository: { host: "forge.example.com", path: `${org}/docs` },
  workspace_snapshots: true,
  agent_workspace_base: null,
  created_at: "2026-10-03T10:00:00Z",
  created_by: PEOPLE[org].id,
  updated_at: "2026-10-03T10:00:00Z",
  updated_by: PEOPLE[org].id,
});
const HELD = { a: agentProject("a", "Ajax docs"), b: agentProject("b", "Beta docs") };

function answer(call: Call): unknown {
  const held = HELD[net.org];
  if (call.method === "GET" && call.path.startsWith("/v1/agent-projects?")) return [held];
  if (call.path.startsWith(`/v1/agent-projects/${held.id}`)) {
    if (call.method === "GET") return held;
    if (call.method === "PUT") return { agent_project_id: held.id, version: 2, updated_at: "2026-10-03T11:00:00Z", updated_by: PEOPLE[net.org].id };
    if (call.method === "PATCH") return { ...held, name: (call.body as { name: string }).name };
  }
  if (call.method === "POST" && call.path === "/v1/agent-projects") return { ...held, id: "pnew" };
  return notFound(call.path);
}

const routes = [
  { path: "/settings/agent-projects", Component: AgentProjectsPage },
  { path: "/settings/agent-projects/:agentProjectId", Component: AgentProjectPage },
];

beforeEach(() => Object.assign(net, newNet(), { answer }));
afterEach(unmount);

describe("the agent projects list", () => {
  it("shows the org's own agent projects and none of another's", async () => {
    await mount(routes, "/settings/agent-projects");
    expect(container.querySelector("table[aria-label='Agent projects']")!.textContent).toContain("Ajax docs");
    expect(container.textContent).toContain("forge.example.com/a/docs");
    expect(container.textContent).not.toContain("Beta docs");
  });

  it("makes an agent project bound to the repository typed", async () => {
    const router = await mount(routes, "/settings/agent-projects");
    await enter("Name", "Docs");
    await enter("Repository", "https://forge.example.com/a/docs.git");
    await press("Make the agent project");
    expect(writes(net)).toEqual([{ method: "POST", path: "/v1/agent-projects", body: { name: "Docs", repository: { host: "forge.example.com", path: "a/docs" }, workspace_snapshots: true } }]);
    expect(router.state.location.pathname).toBe("/settings/agent-projects/pnew");
  });

  it("offers no form to a member who does not manage the org", async () => {
    net.role = "member";
    await mount(routes, "/settings/agent-projects");
    expect(container.querySelector("form[aria-label='New agent project']")).toBeNull();
    expect(container.textContent).toContain("Ajax docs");
  });
});

describe("an agent project's page", () => {
  it("shows nothing of an agent project another org holds", async () => {
    await mount(routes, "/settings/agent-projects/pb");
    expect(container.querySelector("h1")!.textContent).toBe("No agent project here");
    expect(container.textContent).not.toContain("Beta docs");
    expect(writes(net)).toEqual([]);
  });

  it("sends the credential once and never shows it back", async () => {
    await mount(routes, "/settings/agent-projects/pa");
    expect(container.querySelector("h1")!.textContent).toBe("Ajax docs");
    await enter("User", "reader");
    await enter("Password or token", SECRET);
    expect(field("Password or token")!.getAttribute("type")).toBe("password");
    await press("Save the credential");
    expect(writes(net)).toEqual([{ method: "PUT", path: "/v1/agent-projects/pa/credential", body: { username: "reader", password: SECRET } }]);
    expect(field("Password or token")!.value).toBe("");
    expect(container.innerHTML).not.toContain(SECRET);
    expect(container.querySelector("[data-credential]")!.textContent).toMatch(/^A credential is set: by Ada, .+\. It is never shown again\.$/);
  });

  it("offers a member who does not manage the org no credential, rename, or removal", async () => {
    net.role = "viewer";
    await mount(routes, "/settings/agent-projects/pa");
    expect(container.textContent).toContain("forge.example.com/a/docs");
    expect(container.querySelectorAll("form")).toHaveLength(0);
    expect(buttons()).not.toContain("Remove the agent project");
  });

  it("asks before it removes", async () => {
    await mount(routes, "/settings/agent-projects/pa");
    await press("Remove the agent project");
    expect(container.querySelector("[role='alertdialog']")!.textContent).toContain("Remove Ajax docs?");
    expect(writes(net)).toEqual([]);
  });
});
