// @vitest-environment jsdom
// The projects list and a project's page over a fake transport that answers
// as the API does: each org's member reads its own org's projects, and a
// project another org holds answers 404. A member who does not manage the
// org is offered no form. The read credential's password goes out once, in
// the write, and is never on the page after it: not in a field, not in the
// text.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectView } from "@acme/client";
import { buttons, container, enter, field, mount, newNet, notFound, PEOPLE, press, unmount, writes, type Call } from "../screenTesting";
import { ProjectPage } from "./ProjectPage";
import { ProjectsPage } from "./ProjectsPage";

const net = vi.hoisted(() => ({}) as ReturnType<typeof newNet>);
vi.mock("../../app/api", async () => (await import("../screenTesting")).fakeApi(net));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const SECRET = "ghp_never-on-a-screen-1234";

const project = (org: "a" | "b", name: string): ProjectView => ({
  id: `p${org}`,
  name,
  repository: { host: "forge.example.com", path: `${org}/docs` },
  created_at: "2026-10-03T10:00:00Z",
  created_by: PEOPLE[org].id,
  updated_at: "2026-10-03T10:00:00Z",
  updated_by: PEOPLE[org].id,
});
const HELD = { a: project("a", "Ajax docs"), b: project("b", "Beta docs") };

function answer(call: Call): unknown {
  const held = HELD[net.org];
  if (call.method === "GET" && call.path.startsWith("/v1/projects?")) return [held];
  if (call.path.startsWith(`/v1/projects/${held.id}`)) {
    if (call.method === "GET") return held;
    if (call.method === "PUT") return { project_id: held.id, version: 2, updated_at: "2026-10-03T11:00:00Z", updated_by: PEOPLE[net.org].id };
    if (call.method === "PATCH") return { ...held, name: (call.body as { name: string }).name };
  }
  if (call.method === "POST" && call.path === "/v1/projects") return { ...held, id: "pnew" };
  return notFound(call.path);
}

const routes = [
  { path: "/settings/projects", Component: ProjectsPage },
  { path: "/settings/projects/:projectId", Component: ProjectPage },
];

beforeEach(() => Object.assign(net, newNet(), { answer }));
afterEach(unmount);

describe("the projects list", () => {
  it("shows the org's own projects and none of another's", async () => {
    await mount(routes, "/settings/projects");
    expect(container.querySelector("table[aria-label='Projects']")!.textContent).toContain("Ajax docs");
    expect(container.textContent).toContain("forge.example.com/a/docs");
    expect(container.textContent).not.toContain("Beta docs");
  });

  it("makes a project bound to the repository typed", async () => {
    const router = await mount(routes, "/settings/projects");
    await enter("Name", "Docs");
    await enter("Repository", "https://forge.example.com/a/docs.git");
    await press("Make the project");
    expect(writes(net)).toEqual([{ method: "POST", path: "/v1/projects", body: { name: "Docs", repository: { host: "forge.example.com", path: "a/docs" } } }]);
    expect(router.state.location.pathname).toBe("/settings/projects/pnew");
  });

  it("offers no form to a member who does not manage the org", async () => {
    net.role = "member";
    await mount(routes, "/settings/projects");
    expect(container.querySelector("form[aria-label='New project']")).toBeNull();
    expect(container.textContent).toContain("Ajax docs");
  });
});

describe("a project's page", () => {
  it("shows nothing of a project another org holds", async () => {
    await mount(routes, "/settings/projects/pb");
    expect(container.querySelector("h1")!.textContent).toBe("No project here");
    expect(container.textContent).not.toContain("Beta docs");
    expect(writes(net)).toEqual([]);
  });

  it("sends the credential once and never shows it back", async () => {
    await mount(routes, "/settings/projects/pa");
    expect(container.querySelector("h1")!.textContent).toBe("Ajax docs");
    await enter("User", "reader");
    await enter("Password or token", SECRET);
    expect(field("Password or token")!.getAttribute("type")).toBe("password");
    await press("Save the credential");
    expect(writes(net)).toEqual([{ method: "PUT", path: "/v1/projects/pa/credential", body: { username: "reader", password: SECRET } }]);
    expect(field("Password or token")!.value).toBe("");
    expect(container.innerHTML).not.toContain(SECRET);
    expect(container.querySelector("[data-credential]")!.textContent).toMatch(/^A credential is set: by Ada, .+\. It is never shown again\.$/);
  });

  it("offers a member who does not manage the org no credential, rename, or removal", async () => {
    net.role = "viewer";
    await mount(routes, "/settings/projects/pa");
    expect(container.textContent).toContain("forge.example.com/a/docs");
    expect(container.querySelectorAll("form")).toHaveLength(0);
    expect(buttons()).not.toContain("Remove the project");
  });

  it("asks before it removes", async () => {
    await mount(routes, "/settings/projects/pa");
    await press("Remove the project");
    expect(container.querySelector("[role='alertdialog']")!.textContent).toContain("Remove Ajax docs?");
    expect(writes(net)).toEqual([]);
  });
});
