// @vitest-environment jsdom
// The agent playbooks page over a fake transport that answers as the API does: a
// name is read in the member's own org alone, so another org's agent playbook is
// no agent playbook here. Only a member who may write is offered the form. What
// the lever checks found in a version shows beside it, and never stops it;
// a version they never read says so.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AgentPlaybookView } from "@acme/client";
import { buttons, container, enter, mount, newNet, notFound, PEOPLE, press, unmount, writes, type Call } from "../screenTesting";
import { AgentPlaybooksPage } from "./AgentPlaybooksPage";

const net = vi.hoisted(() => ({}) as ReturnType<typeof newNet>);
vi.mock("../../app/api", async () => (await import("../screenTesting")).fakeApi(net));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const agentPlaybook = (org: "a" | "b", name: string): AgentPlaybookView => ({
  id: `pb${org}`,
  name,
  version: 2,
  description: `What ${org} does on a release.`,
  body: "# Steps\n\n1. Read the **log**.",
  gates: [{ tool: "git_push", authorization_class: null, decision: "approve" }],
  published_by: PEOPLE[org].id,
  created_at: "2026-10-03T10:00:00Z",
  findings: [{ check: "unknown_name", detail: "names the tool “git_push”, which no kind it reaches holds", excerpt: "git_push" }],
});
const HELD: Record<"a" | "b", AgentPlaybookView> = { a: agentPlaybook("a", "ajax-release"), b: agentPlaybook("b", "beta-release") };

function answer(call: Call): unknown {
  const held = HELD[net.org];
  if (call.method === "GET" && call.path === `/v1/agent-playbooks/${held.name}`) return held;
  if (call.method === "POST" && call.path === "/v1/agent-playbooks") return { ...held, ...(call.body as object), version: 1 };
  return notFound(call.path);
}

const routes = [{ path: "/agent-playbooks", Component: AgentPlaybooksPage }];

beforeEach(() => Object.assign(net, newNet(), { answer }));
afterEach(unmount);

it("opens the org's agent playbook by name, its steps as Markdown and its gates in words", async () => {
  await mount(routes, "/agent-playbooks?name=ajax-release");
  const shown = container.querySelector("[data-agent-playbook]")!;
  expect(container.querySelector("#agent_playbook h2")!.textContent).toBe("ajax-release, version 2");
  expect(shown.querySelector("strong")!.textContent).toBe("log");
  expect(container.querySelector("ul[aria-label='Gates']")!.textContent).toBe("a call to git_push waits for a person's approval");
  expect(container.querySelector("ul[aria-label='What the checks found']")!.textContent).toBe(
    "A name no kind holds: names the tool “git_push”, which no kind it reaches holds “git_push”",
  );
});

it("says when the checks found nothing in a version", async () => {
  HELD.a = { ...HELD.a, findings: [] };
  await mount(routes, "/agent-playbooks?name=ajax-release");
  expect(container.querySelector("ul[aria-label='What the checks found']")).toBeNull();
  expect(container.textContent).toContain("The checks found nothing to read again.");
  HELD.a = agentPlaybook("a", "ajax-release");
});

it("says a version the checks never read was not checked, never that they found nothing", async () => {
  HELD.a = { ...HELD.a, findings: null };
  await mount(routes, "/agent-playbooks?name=ajax-release");
  expect(container.querySelector("ul[aria-label='What the checks found']")).toBeNull();
  expect(container.textContent).toContain("The checks have not read this version: it was published before they ran.");
  expect(container.textContent).not.toContain("The checks found nothing to read again.");
  HELD.a = agentPlaybook("a", "ajax-release");
});

it("finds no agent playbook another org holds", async () => {
  await mount(routes, "/agent-playbooks?name=beta-release");
  expect(container.textContent).toContain("The org has no agent playbook named beta-release.");
  expect(container.textContent).not.toContain("What b does");
});

it("publishes a name's next version with its gates", async () => {
  await mount(routes, "/agent-playbooks");
  await enter("Name", "release-notes");
  await enter("Description", "Notes for a release.");
  await enter("Steps (Markdown)", "1. Read the log.");
  await enter("Gates, one a line", "deny class network");
  await press("Publish");
  expect(writes(net)).toEqual([
    {
      method: "POST",
      path: "/v1/agent-playbooks",
      body: { name: "release-notes", description: "Notes for a release.", body: "1. Read the log.", gates: [{ decision: "deny", authorization_class: "network" }] },
    },
  ]);
});

it("refuses a gate that is not one, and sends nothing", async () => {
  await mount(routes, "/agent-playbooks");
  await enter("Name", "release-notes");
  await enter("Description", "Notes for a release.");
  await enter("Steps (Markdown)", "1. Read the log.");
  await enter("Gates, one a line", "allow tool git_push");
  await press("Publish");
  expect(container.querySelector("[role='alert']")!.textContent).toContain("Line 1 of the gates is not a gate");
  expect(writes(net)).toEqual([]);
});

it("offers a viewer no form", async () => {
  net.role = "viewer";
  await mount(routes, "/agent-playbooks?name=ajax-release");
  expect(container.querySelector("form[aria-label='Publish an agent playbook']")).toBeNull();
  expect(buttons()).not.toContain("Write the next version");
});
