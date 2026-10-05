// @vitest-environment jsdom
// The shell every signed-in page sits in: the left bar (the org chip, the
// search, New session, the slot's entries, the sessions grouped by what
// they ask, each parent folding its sub-agents, and the user chip), the
// search over the whole app, its keys, the toast a session raises when it
// starts to need its person, and the support dock beside the page.
// The real shell, chips, and menus run over a fake transport; the pages
// behind the routes are stand-ins.
import { act, createElement, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentSessionView, MeView, OrgView, UserView } from "@acme/client";
import { PREFERENCES_STORAGE_KEY, usePreferencesStore } from "../../store/preferences";
import { useSessionStore } from "../../store/session";
import { useSupportStore } from "../../store/support";
import { EMPTY_PRODUCT, type PortalProduct } from "../product";
import { queryClient } from "../queryClient";
import { SlotProvider } from "../slot";
import { Shell } from "./Shell";
import { DEFAULT_FILTER } from "./shellModel";

const net = vi.hoisted(() => ({
  posts: [] as { path: string; body: unknown }[],
  gets: [] as string[],
  logout: { provider_logout_url: null as string | null },
  permissions: ["read", "write"] as string[],
  sessions: [] as unknown[],
  started: 0,
}));

const at = "2026-10-05T10:00:00Z";
const user = { id: "u1", email: "owner@example.test", display_name: "Owner", created_at: at } as UserView;
const org = { id: "o1", name: "Ajax", slug: "ajax", kind: "team", created_at: at, deleted_at: null } as OrgView;

const session = (id: string, over: Partial<AgentSessionView> = {}): AgentSessionView => ({
  id,
  title: id,
  kind: "engineer",
  kind_version: 1,
  status: "idle",
  park: null,
  parent_id: null,
  root_id: id,
  created_by: "u1",
  created_at: at,
  archived_at: null,
  deleted_at: null,
  ...over,
});

vi.mock("../api", () => ({
  api: {
    get: (path: string) => {
      net.gets.push(path);
      if (path === "/v1/me") {
        return Promise.resolve({ app: "portal", role: "owner", permissions: net.permissions, user, org } as MeView);
      }
      if (path.startsWith("/v1/auth/memberships")) return Promise.resolve({ items: [{ org, user, role: "owner" }], next_cursor: null });
      const one = /^\/v1\/agent-sessions\/([^/?]+)(\/steps)?/.exec(path);
      if (one) {
        const found = (net.sessions as AgentSessionView[]).find((each) => each.id === one[1]);
        if (!found) return Promise.reject(new Error(`no session ${one[1]}`));
        return Promise.resolve(one[2] ? { items: [], has_more: false } : found);
      }
      if (path.startsWith("/v1/agent-sessions?status=parked")) {
        const parked = (net.sessions as AgentSessionView[]).filter((each) => each.status === "parked");
        return Promise.resolve({ items: parked, next_cursor: null });
      }
      if (path.startsWith("/v1/agent-sessions")) return Promise.resolve({ items: net.sessions, next_cursor: null });
      if (path.startsWith("/v1/approvals")) {
        return Promise.resolve({ items: [{ session_id: "asks", tool: "run_command", seq: 3 }], next_cursor: null });
      }
      return Promise.reject(new Error(`no read for ${path}`));
    },
    post: (path: string, body: unknown) => {
      net.posts.push({ path, body });
      if (path === "/v1/auth/logout") return Promise.resolve(net.logout);
      if (path === "/v1/agent-sessions") {
        net.started += 1;
        const started = session(`support-${net.started}`, { kind: "platform_assistant", title: "Support" });
        net.sessions = [...net.sessions, started];
        return Promise.resolve(started);
      }
      if (/^\/v1\/agent-sessions\/[^/]+\/messages$/.test(path)) return Promise.resolve({});
      return Promise.reject(new Error(`no answer for ${path}`));
    },
  },
}));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const container = document.createElement("div");
document.body.append(container);
let root: ReturnType<typeof createRoot>;
let router: ReturnType<typeof createMemoryRouter>;

const SLOT: PortalProduct = {
  ...EMPTY_PRODUCT,
  nav: [
    { id: "automations", label: "Automations", icon: null, to: "/automations", tip: "Automations" },
    { id: "knowledge", label: "Knowledge", icon: null, to: "/knowledge", tip: "Knowledge", count: () => 2 },
  ],
  settings: [
    { group: "Agents", id: "projects", label: "Projects", icon: null, about: "Repositories", routes: [{ path: "/settings/projects" }] },
    { group: "Security", id: "api-keys", label: "API keys", icon: null, about: "Keys a program calls with", routes: [{ path: "/settings/api-keys" }] },
  ],
  agents: [{ kind: "engineer", label: "Engineer", about: "Changes code." }],
};

const frame = ({ children }: { children?: ReactNode }) =>
  createElement(SlotProvider, { slot: SLOT, children: createElement(Shell, { children: children ?? createElement(Outlet) }) });
const page = (name: string) => () => createElement("main", null, name);

const settle = async () => {
  for (let turn = 0; turn < 8; turn += 1) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
};
const q = <T extends Element = HTMLElement>(selector: string) => container.querySelector(selector) as T | null;
const trigger = () => q<HTMLButtonElement>("button[aria-label^='Account']")!;
const menu = () => q("[role='menu'][aria-label='Account']");
const label = (node: Element) => node.querySelector(".acme-menu-label")?.textContent ?? node.textContent;
const item = (text: string) =>
  [...container.querySelectorAll<HTMLElement>("[role='menuitem'], [role='menuitemradio']")].find((node) => label(node) === text)!;
const key = (target: Element, name: string, mods: KeyboardEventInit = {}) =>
  act(async () => { target.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true, ...mods })); });
const group = (name: string) => [...(q(`ul[aria-label='${name}']`)?.children ?? [])].map((li) => li.querySelector(".acme-row-title")?.textContent);

async function mount(path = "/") {
  router = createMemoryRouter(
    [
      {
        Component: frame,
        children: [
          { path: "/", Component: page("home") },
          { path: "/settings", Component: page("settings") },
          { path: "/sessions", Component: page("sessions") },
          { path: "/sessions/:id", Component: page("one session") },
          { path: "/settings/*", Component: page("a section") },
          { path: "/automations", Component: page("automations") },
          { path: "/knowledge", Component: page("knowledge") },
        ],
      },
    ],
    { initialEntries: [path] },
  );
  await act(async () => {
    root.render(createElement(QueryClientProvider, { client: queryClient }, createElement(RouterProvider, { router })));
  });
  await settle();
}

beforeEach(async () => {
  queryClient.clear();
  net.posts.length = 0;
  net.gets.length = 0;
  net.logout = { provider_logout_url: null };
  net.permissions = ["read", "write"];
  net.sessions = [];
  net.started = 0;
  localStorage.clear();
  useSupportStore.setState({ conversations: {} });
  Object.defineProperty(window, "innerWidth", { value: 1440, configurable: true });
  usePreferencesStore.setState({ theme: "system", sidebarFolded: false, sessionFilter: DEFAULT_FILTER, foldedTrees: [] });
  useSessionStore.getState().setSession("ses_ajax", "ajax");
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.render(null));
  useSessionStore.getState().clear();
  vi.unstubAllGlobals();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
});

it("holds the org chip, the search, New session, the slot's entries with their counts, and the user chip", async () => {
  await mount();
  const nav = q("nav[aria-label='Main']")!;
  const links = [...nav.querySelectorAll("a")].map((a) => a.textContent?.trim());
  expect(links).toEqual(["New session", "Automations", "Knowledge2"]);
  expect(q("aside")!.textContent).toContain("Search");
  expect(trigger().textContent).toContain("Owner");
  expect(trigger().textContent).toContain("Ajax");
  expect(q("[role='status']")!.getAttribute("aria-label")).toMatch(/^live updates/);
});

it("says there are no sessions yet, and reads no held call while none waits", async () => {
  await mount();
  expect(q("aside")!.textContent).toContain("No sessions yet. Describe a task on Home.");
  expect(net.gets.some((path) => path.startsWith("/v1/approvals"))).toBe(false);
});

it("groups the sessions into Needs you, Running, and Recent, a sub-agent under its parent, the held tool named", async () => {
  net.sessions = [
    session("asks", { status: "parked", park: { reason: "person", unlock: "approval", retry_at: null } }),
    session("runs", { status: "running" }),
    session("child", { parent_id: "runs", root_id: "runs", status: "running" }),
    session("done"),
  ];
  await mount();
  expect(group("Needs you")).toEqual(["asks"]);
  expect(group("Running")).toEqual(["runs"]);
  expect(group("Recent")).toEqual(["done"]);
  expect(q("ul[aria-label='Sub-agents of runs']")!.textContent).toContain("child");
  expect(q("ul[aria-label='Needs you']")!.textContent).toContain("Needs your decision: run_command");
  const row = [...container.querySelectorAll<HTMLAnchorElement>(".acme-side-row")].find((a) => a.textContent?.includes("done"))!;
  expect(row.getAttribute("href")).toBe("/sessions/done");
});

it("folds a parent row's sub-agents, saying how many and how many need the person, and keeps the fold", async () => {
  net.sessions = [
    session("runs", { status: "parked", park: { reason: "children", unlock: "children", retry_at: null } }),
    session("reads", { parent_id: "runs", root_id: "runs", status: "running" }),
    session("asks", { parent_id: "runs", root_id: "runs", status: "parked", park: { reason: "person", unlock: "answer", retry_at: null } }),
  ];
  await mount();
  const fold = q<HTMLButtonElement>("button[aria-label='Fold the sub-agents of runs']")!;
  expect(fold.getAttribute("aria-expanded")).toBe("true");
  expect(q("ul[aria-label='Sub-agents of runs']")!.textContent).toContain("reads");
  await act(async () => fold.click());
  expect(q("ul[aria-label='Sub-agents of runs']")).toBeNull();
  expect(q(".acme-row-tree")!.textContent).toBe("2 sub-agents · 1 needs you");
  expect(usePreferencesStore.getState().foldedTrees).toEqual(["runs"]);
  await act(async () => q<HTMLButtonElement>("button[aria-label='Show the sub-agents of runs']")!.click());
  expect(q("ul[aria-label='Sub-agents of runs']")!.textContent).toContain("asks");
});

it("raises a toast on any page when a sub-agent of the person's starts to need them, which opens it", async () => {
  const running = [session("runs", { status: "running" }), session("asks", { title: "Check every caller", parent_id: "runs", root_id: "runs", status: "running" })];
  net.sessions = running;
  await mount("/settings");
  expect(q(".acme-needs-toasts")).toBeNull();
  net.sessions = running.map((one) => (one.id === "asks" ? { ...one, status: "parked", park: { reason: "person", unlock: "answer", retry_at: null } } : one));
  await act(async () => queryClient.invalidateQueries());
  await settle();
  const toast = q(".acme-needs-toasts")!;
  expect(toast.textContent).toContain("Check every caller");
  expect(toast.textContent).toContain("Answer its question");
  const open = [...toast.querySelectorAll("button")].find((button) => button.textContent === "Open")!;
  await act(async () => open.click());
  await settle();
  expect(router.state.location.pathname).toBe("/sessions/asks");
  expect(q(".acme-needs-toasts")).toBeNull();
});

it("narrows the sessions by the filter it keeps, and says so when none matches", async () => {
  net.sessions = [session("theirs", { created_by: "u2" })];
  usePreferencesStore.setState({ sessionFilter: { ...DEFAULT_FILTER, owner: "mine" } });
  await mount();
  expect(q("aside")!.textContent).toContain("No session matches the filter.");
  expect(q("button[aria-label='Filter the sessions (on)']")).not.toBeNull();
  const show = [...container.querySelectorAll("button")].find((b) => b.textContent === "Show every session")!;
  await act(async () => show.click());
  expect(group("Recent")).toEqual(["theirs"]);
});

it("goes home from the org's name, and to Settings and the members from the chip's menu", async () => {
  net.permissions = ["read", "write", "manage_members"];
  await mount();
  const home = [...container.querySelectorAll("a")].find((a) => a.textContent?.includes("Ajax"))!;
  expect(home.getAttribute("href")).toBe("/");
  await act(async () => home.click());
  expect(router.state.location.pathname).toBe("/");

  await act(async () => q<HTMLButtonElement>("button[aria-label='Create an organization']")!.click());
  expect(q("[role='menu'][aria-label='Organizations']")).not.toBeNull();
  expect(item("New organization…")).toBeDefined();
  await act(async () => item("Invite members").click());
  expect(router.state.location.pathname).toBe("/settings/members");
});

it("offers Invite members only to a member who may manage them", async () => {
  await mount();
  await act(async () => q<HTMLButtonElement>("button[aria-label='Create an organization']")!.click());
  expect(item("Settings")).toBeDefined();
  expect(item("Invite members")).toBeUndefined();
});

it("opens the user chip's menu on a click, not on hover, with Settings, the theme, the shortcuts, the documentation, and Sign out", async () => {
  await mount();
  await act(async () => { trigger().dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); });
  expect(menu()).toBeNull();
  await act(async () => trigger().click());
  expect(trigger().getAttribute("aria-expanded")).toBe("true");
  expect(menu()!.textContent).toContain("owner@example.test");
  const items = [...menu()!.querySelectorAll("[role^='menuitem']")].map(label);
  expect(items).toEqual(["Settings", "Profile and preferences", "System", "Light", "Dark", "Keyboard shortcuts", "Documentation ↗", "Sign out"]);
  expect(item("Settings").querySelector("kbd")!.textContent).toBe("⌘,");
  expect(document.activeElement).toBe(item("Settings"));
  const drawings = [...menu()!.querySelectorAll<HTMLElement>("[role^='menuitem']")].map(
    (node) => node.querySelector(".acme-menu-icon[aria-hidden='true'] svg")?.innerHTML,
  );
  expect(drawings.every(Boolean)).toBe(true);
});

it("moves by the arrows, closes on Escape, and gives the keyboard back to its button", async () => {
  await mount();
  trigger().focus();
  await key(trigger(), "ArrowDown");
  expect(document.activeElement).toBe(item("Settings"));
  await key(document.activeElement!, "ArrowDown");
  expect(document.activeElement).toBe(item("Profile and preferences"));
  await key(document.activeElement!, "ArrowDown");
  expect(document.activeElement).toBe(item("System"));
  await key(document.activeElement!, "End");
  expect(document.activeElement).toBe(item("Sign out"));
  await key(document.activeElement!, "Escape");
  expect(menu()).toBeNull();
  expect(document.activeElement).toBe(trigger());
});

it("closes on a click anywhere else, and goes to Settings from the menu", async () => {
  await mount("/");
  await act(async () => trigger().click());
  await act(async () => { q("main")!.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(menu()).toBeNull();
  await act(async () => trigger().click());
  await act(async () => item("Settings").click());
  expect(router.state.location.pathname).toBe("/settings");
});

it("marks the theme in use, applies a pick, and keeps it across visits", async () => {
  await mount();
  await act(async () => trigger().click());
  expect(item("System").getAttribute("aria-checked")).toBe("true");
  await act(async () => item("Dark").click());
  expect(usePreferencesStore.getState().theme).toBe("dark");
  expect(item("Dark").getAttribute("aria-checked")).toBe("true");
  expect(JSON.parse(localStorage.getItem(PREFERENCES_STORAGE_KEY)!).state.theme).toBe("dark");
});

it("opens the keyboard shortcuts from the menu, and closes them on Escape", async () => {
  await mount();
  await act(async () => trigger().click());
  await act(async () => item("Keyboard shortcuts").click());
  const dialog = q("[role='dialog'][aria-modal='true']")!;
  expect(dialog.textContent).toContain("⌘K");
  await key(dialog, "Escape");
  expect(q("[role='dialog'][aria-modal='true']")).toBeNull();
});

it("searches the whole app on Cmd-K: what is typed starts a session on Home, and a setting or a session opens", async () => {
  net.sessions = [session("Tidy the docs")];
  await mount();
  await key(window as unknown as Element, "k", { metaKey: true });
  const field = q<HTMLInputElement>("input[role='combobox']")!;
  expect(field.placeholder).toBe("Search sessions, settings, and actions");
  const options = () => [...container.querySelectorAll("[role='option']")].map((o) => o.querySelector(".acme-palette-label")?.textContent);
  expect(options()).toEqual(expect.arrayContaining(["New session", "Automations", "Projects", "Tidy the docs"]));
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, "Fix the build");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(options()[0]).toBe("Start a session: Fix the build");
  await key(field, "Enter");
  expect(router.state.location.pathname).toBe("/");
  expect(router.state.location.state).toEqual({ prompt: "Fix the build" });
});

it("folds the left bar on Cmd-B and keeps it folded, and opens it again from its button", async () => {
  await mount();
  await key(window as unknown as Element, "b", { metaKey: true });
  expect(q("aside")).toBeNull();
  expect(usePreferencesStore.getState().sidebarFolded).toBe(true);
  await act(async () => q<HTMLButtonElement>("button[aria-label='Open sidebar']")!.click());
  expect(q("aside")).not.toBeNull();
});

it("opens Settings on Cmd-comma", async () => {
  await mount("/");
  await key(window as unknown as Element, ",", { metaKey: true });
  expect(router.state.location.pathname).toBe("/settings");
});

it("puts Settings' own bar in the left bar's place inside Settings: back to the app, the search, and the sections by group", async () => {
  await mount("/settings/projects");
  expect(q("aside[aria-label='Sidebar']")).toBeNull();
  const bar = q("aside[aria-label='Settings sidebar']")!;
  const sections = () => [...bar.querySelectorAll("nav[aria-label='Settings'] a")].map((a) => [a.textContent, a.getAttribute("href")]);
  expect(sections()).toEqual([
    ["Overview", "/settings"],
    ["Projects", "/settings/projects"],
    ["API keys", "/settings/api-keys"],
  ]);
  expect([...bar.querySelectorAll("h2")].map((h) => h.textContent)).toEqual(["Agents", "Security"]);
  expect(bar.querySelector("a[aria-current='page']")!.textContent).toBe("Projects");

  const search = bar.querySelector<HTMLInputElement>("input[type='search']")!;
  expect(search.placeholder).toBe("e.g. API keys");
  await key(window as unknown as Element, "/");
  expect(document.activeElement).toBe(search);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(search, "keys");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(sections()).toEqual([
    ["Overview", "/settings"],
    ["API keys", "/settings/api-keys"],
  ]);
  await key(search, "Enter");
  expect(router.state.location.pathname).toBe("/settings/api-keys");

  await act(async () => [...bar.querySelectorAll("a")].find((a) => a.textContent === "Back to app")!.click());
  expect(router.state.location.pathname).toBe("/");
  expect(q("aside[aria-label='Settings sidebar']")).toBeNull();
  expect(q("aside[aria-label='Sidebar']")).not.toBeNull();
});

it("signs out: the server session first, then the token here", async () => {
  await mount();
  await act(async () => trigger().click());
  await act(async () => item("Sign out").click());
  await settle();
  expect(net.posts.map((post) => post.path)).toEqual(["/v1/auth/logout"]);
  expect(useSessionStore.getState().token).toBeNull();
});

it("goes to the identity provider's logout when the server names one", async () => {
  await mount();
  const assign = vi.fn();
  vi.stubGlobal("location", { origin: "http://localhost:5173", assign });
  net.logout = { provider_logout_url: "https://api.workos.com/user_management/sessions/logout?session_id=s1" };
  await act(async () => trigger().click());
  await act(async () => item("Sign out").click());
  await settle();
  expect(net.posts[0]!.body).toEqual({ return_to: "http://localhost:5173/signed-out" });
  expect(useSessionStore.getState().token).toBeNull();
  expect(assign).toHaveBeenCalledWith("https://api.workos.com/user_management/sessions/logout?session_id=s1");
});

describe("the support dock", () => {
  const dock = () => q("aside[aria-label='Support']");
  const ask = () => q<HTMLButtonElement>("button[aria-label='Ask support']")!;
  const field = () => q<HTMLTextAreaElement>("aside[aria-label='Support'] textarea")!;
  const typeIn = (text: string) =>
    act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(field(), text);
      field().dispatchEvent(new Event("input", { bubbles: true }));
    });
  const send = async () => {
    await act(async () => q<HTMLButtonElement>("aside[aria-label='Support'] button[aria-label='Send']")!.click());
    await settle();
  };

  it('opens from "?" beside the user chip, from Cmd-/, and from "Ask support" in the search; its close button and Esc close it', async () => {
    await mount("/sessions");
    expect(dock()).toBeNull();
    expect(ask().closest(".acme-sidebar-foot")).not.toBeNull();
    await act(async () => ask().click());
    expect(dock()!.dataset.mode).toBe("side");
    expect(ask().getAttribute("aria-expanded")).toBe("true");
    await act(async () => q<HTMLButtonElement>("button[aria-label='Close support']")!.click());
    expect(dock()).toBeNull();

    await key(window as unknown as Element, "/", { metaKey: true });
    expect(dock()).not.toBeNull();
    await key(field(), "Escape");
    expect(dock()).toBeNull();

    await key(window as unknown as Element, "k", { metaKey: true });
    const option = [...container.querySelectorAll<HTMLElement>("[role='option']")].find((o) => o.querySelector(".acme-palette-label")?.textContent === "Ask support")!;
    await act(async () => option.click());
    expect(dock()).not.toBeNull();
    expect(router.state.location.pathname).toBe("/sessions");
  });

  it("keeps its draft while the main area moves to another page beside it", async () => {
    await mount("/sessions");
    await act(async () => ask().click());
    await typeIn("Why is my session parked?");
    await act(async () => router.navigate("/automations"));
    expect(container.textContent).toContain("automations");
    expect(dock()!.dataset.mode).toBe("side");
    expect(field().value).toBe("Why is my session parked?");
  });

  it("is a sheet under 1100 pixels, which a move to another page closes and which opens again with its draft", async () => {
    Object.defineProperty(window, "innerWidth", { value: 900, configurable: true });
    await mount("/sessions");
    await act(async () => ask().click());
    expect(dock()!.dataset.mode).toBe("sheet");
    await typeIn("Where are the API keys?");
    await act(async () => router.navigate("/knowledge"));
    expect(dock()).toBeNull();
    await act(async () => ask().click());
    expect(field().value).toBe("Where are the API keys?");
  });

  it("expands over the main area, and a move to another page returns it beside the page", async () => {
    await mount("/sessions");
    await act(async () => ask().click());
    await act(async () => q<HTMLButtonElement>("button[aria-label='Expand']")!.click());
    expect(dock()!.dataset.mode).toBe("expanded");
    expect(q(".acme-main")!.hidden).toBe(true);
    await act(async () => router.navigate("/automations"));
    expect(dock()!.dataset.mode).toBe("side");
    expect(q(".acme-main")!.hidden).toBe(false);
  });

  it("starts the person's conversation on the platform assistant with their first message, the page riding as data, and continues it", async () => {
    await mount("/sessions/s1");
    await act(async () => ask().click());
    await typeIn("Why is this one stuck?");
    await send();
    expect(net.posts.map((post) => post.path)).toEqual(["/v1/agent-sessions", "/v1/agent-sessions/support-1/messages"]);
    expect(net.posts[0]!.body).toEqual({ kind: "platform_assistant", title: "Support" });
    const text = (net.posts[1]!.body as { text: string }).text;
    expect(text.split("\n").slice(0, 3)).toEqual(["Why is this one stuck?", "", "~~~page"]);
    expect(JSON.parse(text.split("\n")[3]!)).toMatchObject({ path: "/sessions/s1" });
    expect(useSupportStore.getState().conversations["o1/u1"]).toBe("support-1");
    expect(field().value).toBe("");

    await typeIn("And the other one?");
    await send();
    expect(net.posts.map((post) => post.path).slice(2)).toEqual(["/v1/agent-sessions/support-1/messages"]);
  });

  it("never reads another member's session through the dock, nor a session of another kind, and starts the person's own instead", async () => {
    net.sessions = [
      session("theirs", { kind: "platform_assistant", created_by: "u2" }),
      session("engineer", { kind: "engineer" }),
    ];
    for (const kept of ["theirs", "engineer"]) {
      net.gets.length = 0;
      net.posts.length = 0;
      useSupportStore.setState({ conversations: { "o1/u1": kept } });
      await mount("/sessions");
      await act(async () => ask().click());
      await settle();
      expect(net.gets).toContain(`/v1/agent-sessions/${kept}`);
      expect(net.gets.filter((path) => path.startsWith(`/v1/agent-sessions/${kept}/`))).toEqual([]);
      expect(dock()!.textContent).toContain("Ask how the platform works");
      expect(q("aside[aria-label='Support'] a[href^='/sessions/']")).toBeNull();
      await typeIn("Hello");
      await send();
      expect(net.posts[0]!.path).toBe("/v1/agent-sessions");
      expect(net.posts[1]!.path).not.toContain(kept);
      await act(async () => root.render(null));
      queryClient.clear();
    }
  });

  it("continues the person's own conversation, and New conversation starts the next message afresh", async () => {
    net.sessions = [session("work"), session("mine", { kind: "platform_assistant", title: "Support" })];
    useSupportStore.setState({ conversations: { "o1/u1": "mine" } });
    await mount("/sessions");
    await act(async () => ask().click());
    await settle();
    expect(net.gets.some((path) => path.startsWith("/v1/agent-sessions/mine/steps"))).toBe(true);
    expect(q("aside[aria-label='Support'] a[href='/sessions/mine']")!.textContent).toBe("As a session");
    // The left bar lists the work; the conversation is the dock's.
    expect(group("Recent")).toEqual(["work"]);
    await act(async () => q<HTMLButtonElement>("button[aria-label='New conversation']")!.click());
    expect(useSupportStore.getState().conversations["o1/u1"]).toBeUndefined();
    await typeIn("A new question");
    await send();
    expect(net.posts.map((post) => post.path)).toEqual(["/v1/agent-sessions", "/v1/agent-sessions/support-1/messages"]);
  });
});
