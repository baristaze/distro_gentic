// @vitest-environment jsdom
// Home's composer over a fake transport: Send starts a session on the agent
// and the project the chips show, sends it the prompt, and opens it; where a
// project is required and the org has none, it says why and sends nothing;
// a member who may not write starts nothing.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { MeView } from "@acme/client";
import { EMPTY_PRODUCT, type PortalProduct } from "../../app/product";
import { SlotProvider } from "../../app/slot";
import { NO_PROJECT } from "../sessions/sessionsModel";
import { HomePage } from "./HomePage";

const net = vi.hoisted(() => ({
  environment: "local",
  permissions: ["read", "write"] as string[],
  projects: [] as { id: string; name: string }[],
  posts: [] as { path: string; body: unknown }[],
}));

vi.mock("../../app/api", () => ({
  api: {
    get: (path: string) => {
      if (path === "/v1/me") {
        return Promise.resolve({ app: "portal", role: "owner", permissions: net.permissions, user: { id: "u1" }, org: { id: "o1" } } as unknown as MeView);
      }
      if (path.startsWith("/v1/projects?")) return Promise.resolve(net.projects);
      return Promise.reject(new Error(`no read for ${path}`));
    },
    post: (path: string, body?: unknown) => {
      net.posts.push({ path, body });
      if (path === "/v1/agent-sessions") return Promise.resolve({ id: "s1" });
      if (path === "/v1/agent-sessions/s1/messages") return Promise.resolve({ seq: 1 });
      return Promise.reject(new Error(`no answer for ${path}`));
    },
  },
}));
vi.mock("../../app/config", () => ({ runtimeConfig: () => ({ environment: net.environment }) }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const SLOT: PortalProduct = {
  ...EMPTY_PRODUCT,
  agents: [
    { kind: "engineer", label: "Engineer", about: "Changes code." },
    { kind: "platform_assistant", label: "Platform assistant", about: "Answers how the platform works." },
  ],
  examples: { composer: 'Describe a task, e.g. "Fix the failing test"', starters: ["Add a test for leap years", "b", "c"] },
};

const container = document.createElement("div");
document.body.append(container);
let root: ReturnType<typeof createRoot> | null = null;
let router: ReturnType<typeof createMemoryRouter>;

async function settle() {
  for (let turn = 0; turn < 6; turn += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
}

async function open() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  router = createMemoryRouter(
    [
      { path: "/", Component: () => createElement(SlotProvider, { slot: SLOT, children: createElement(HomePage) }) },
      { path: "/sessions/:id", Component: () => createElement("h1", null, "a session") },
    ],
    { initialEntries: ["/"] },
  );
  root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client: queryClient }, createElement(RouterProvider, { router }))));
  await settle();
}

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  Object.assign(net, { environment: "local", permissions: ["read", "write"], projects: [], posts: [] });
});

const box = () => container.querySelector<HTMLTextAreaElement>("textarea")!;
const button = (name: string) => container.querySelector<HTMLButtonElement>(`button[aria-label^='${name}']`)!;
const choice = (text: string) =>
  [...container.querySelectorAll<HTMLElement>("[role='menuitemradio']")].find((node) => node.textContent?.startsWith(text))!;

async function type(text: string) {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(box(), text);
  await act(async () => box().dispatchEvent(new Event("input", { bubbles: true })));
}

it("shows the slot's example in the box, its first agent on the chip, and its starter prompts", async () => {
  await open();
  expect(box().placeholder).toBe('Describe a task, e.g. "Fix the failing test"');
  expect(button("Agent").textContent).toContain("Engineer");
  expect(button("Project").textContent).toContain("No project");
  const starters = [...container.querySelectorAll("ul[aria-label='Starter prompts'] button")];
  expect(starters.map((each) => each.textContent)).toEqual(["Add a test for leap years", "b", "c"]);
  await act(async () => (starters[0] as HTMLButtonElement).click());
  expect(box().value).toBe("Add a test for leap years");
});

it("starts the agent and the project the chips show, sends the prompt, and opens the session", async () => {
  net.environment = "staging";
  net.projects = [
    { id: "p1", name: "Docs" },
    { id: "p2", name: "Site" },
  ];
  await open();
  expect(button("Project").textContent).toContain("Docs");
  await act(async () => button("Agent").click());
  await act(async () => choice("Platform assistant").click());
  await act(async () => button("Project").click());
  await act(async () => choice("Site").click());
  await type("Tidy the docs\nKeep the voice plain.");
  await act(async () => box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", metaKey: true, bubbles: true })));
  await settle();
  expect(net.posts).toEqual([
    { path: "/v1/agent-sessions", body: { title: "Tidy the docs", kind: "platform_assistant", project_id: "p2" } },
    { path: "/v1/agent-sessions/s1/messages", body: { text: "Tidy the docs\nKeep the voice plain." } },
  ]);
  expect(router.state.location.pathname).toBe("/sessions/s1");
});

it("with no project to choose where one is required, says why it cannot start and sends nothing", async () => {
  net.environment = "staging";
  await open();
  expect(container.textContent).toContain(NO_PROJECT);
  await type("Tidy the docs");
  await act(async () => button("Send").click());
  await settle();
  expect(net.posts).toEqual([]);
  expect(container.textContent).toContain(NO_PROJECT);
});

it("asks for a prompt before it starts anything", async () => {
  await open();
  await act(async () => button("Send").click());
  expect(container.textContent).toContain("Describe the task first.");
  expect(net.posts).toEqual([]);
});

it("starts nothing for a member who may not write, and says why", async () => {
  net.permissions = ["read"];
  await open();
  expect(box().disabled).toBe(true);
  expect(button("Send").disabled).toBe(true);
  expect(container.textContent).toContain("Starting one needs the write permission.");
});
