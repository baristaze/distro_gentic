// @vitest-environment jsdom
// Every field teaches: a text field shows a realistic example of what goes
// in while it is empty. Each platform screen mounts in the real routes,
// shell, and slot, over a fake transport that answers as an owner of a team
// org sees it, its record forms open, and no text field on it is without a
// watermark. A field drawn only in a state no fixture reaches (a held call's
// note, a workspace taken over) is held by the scan of every screen's source
// below it.
import { act, createElement, type ReactNode } from "react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, type AgentSessionView, type AutomationView, type KnowledgeView, type MeView, type ProjectView } from "@acme/client";
import { useSessionStore } from "../store/session";
import { MOVED } from "../app/platform";
import { shellRoutes } from "../app/product";
import { queryClient } from "../app/queryClient";
import { routes, SLOT } from "../app/routes";

const at = "2026-10-03T10:00:00Z";
const user = { id: "u1", email: "ada@example.test", display_name: "Ada", created_at: at };
const org = { id: "o1", name: "Ajax", slug: "ajax", kind: "team", created_at: at, deleted_at: null };
const ME = { app: "portal", role: "owner", permissions: ["read", "write", "manage_members", "manage_keys"], user, org } as unknown as MeView;
const page = <T>(items: T[]) => ({ items, next_cursor: null });

const PROJECT: ProjectView = {
  id: "p1",
  name: "Storefront",
  repository: { host: "github.com", path: "your-org/storefront" },
  created_at: at,
  created_by: user.id,
  updated_at: at,
  updated_by: user.id,
};
const AUTOMATION: AutomationView = {
  id: "a1",
  name: "Nightly dependency update",
  trigger: { kind: "schedule", every: "P1D", integrations: [], arrivals: [], effects: [] },
  action: { kind: "start_session", brief: "Update dependencies.", agent_kind: "engineer", title: "Update dependencies", project_id: null, session_id: null, params: {} },
  limits: { cost_cap_micros: 5_000_000, run_cap_micros: 1_000_000, period: "P1D", rate: 10, concurrency: 1, queue: false, queue_depth: 50, hop_limit: 3 },
  runs_as: "creator",
  own_events: false,
  enabled: false,
  created_at: at,
  created_by: user.id,
  updated_at: at,
  updated_by: user.id,
} as AutomationView;
const ENTRY: KnowledgeView = {
  id: "k1",
  title: "How we name migrations",
  trigger: ["migration"],
  text: "Never edit a migration that has shipped.",
  status: "reviewed",
  suggested_by: null,
  reviewed_by: user.id,
  version: 1,
  created_at: at,
  updated_at: at,
} as KnowledgeView;
const SESSION = {
  id: "s1",
  root_id: "s1",
  parent_id: null,
  kind: "engineer",
  kind_version: 1,
  title: "Fix the failing date test",
  status: "idle",
  park: null,
  created_at: at,
  created_by: user.id,
  archived_at: null,
  deleted_at: null,
} as AgentSessionView;

/** A param of a screen's address, as a fixture's id. */
const PARAMS: Record<string, string> = { sessionId: "s1", automationId: "a1", entryId: "k1", projectId: "p1" };

function answer(path: string): unknown {
  const [bare = "", query = ""] = path.split("?");
  if (bare === "/v1/me") return ME;
  if (bare === "/v1/me/identity") return { id: "i1", email: user.email, operator_role: null, created_at: at, time_zone: null };
  if (bare === "/v1/users") return page([user]);
  if (bare === "/v1/memberships") return page([{ id: "m1", user_id: user.id, role: "owner", teams: [] }]);
  if (bare === "/v1/auth/memberships") return page([{ org, user, role: "owner" }]);
  if (bare === "/v1/invitations" || bare === "/v1/api-keys" || bare === "/v1/usage" || bare === "/v1/approvals") return page([]);
  if (bare === "/v1/media/usage") return { bytes: 0, files: 0 };
  if (bare === "/v1/agent-sessions") return query.includes("status=parked") ? page([]) : page([SESSION]);
  if (bare === "/v1/knowledge") return query.includes("status=reviewed") ? [ENTRY] : [];
  if (bare === "/v1/knowledge/k1") return ENTRY;
  if (bare === "/v1/projects") return [PROJECT];
  if (bare === "/v1/projects/p1") return PROJECT;
  if (bare === "/v1/automations") return [AUTOMATION];
  if (bare === "/v1/automations/a1") return AUTOMATION;
  if (bare === "/v1/provider-keys" || bare === "/v1/matrix/options" || bare === "/v1/matrix/choices" || bare === "/v1/events/recent") return [];
  if (bare.startsWith("/v1/agent-sessions/s1")) {
    const part = bare.split("/")[4];
    if (part === undefined) return SESSION;
    if (part === "steps") return { has_more: false, items: [] };
    if (part === "executions" || part === "tool-calls") return page([]);
    if (part === "validations") return [];
    if (part === "usage") return { calls: 0, input: 0, output: 0, thinking: 0, cache_read: 0, cache_write: 0, fills: [] };
  }
  // A playbook not yet published, the principal not yet granted, and every
  // other read: not found, as the API says it.
  throw new ApiError(404, "not_found", `nothing at ${path}`, "req-1");
}

vi.mock("../app/api", () => {
  const send = (path: string) => {
    try {
      return Promise.resolve(answer(path));
    } catch (caught) {
      return Promise.reject(caught);
    }
  };
  return { api: { get: send, post: () => Promise.resolve({}), patch: () => Promise.resolve({}), del: () => Promise.resolve({}), request: () => Promise.resolve({}) } };
});
vi.mock("../app/config", () => ({ runtimeConfig: () => ({ environment: "local", devSignIn: true }) }));
vi.mock("../realtime/RealtimeProvider", () => ({ RealtimeProvider: ({ children }: { children: ReactNode }) => children }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const container = document.createElement("div");
document.body.append(container);
let root: ReturnType<typeof createRoot>;

const settle = async () => {
  for (let turn = 0; turn < 10; turn += 1) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
};

/** A text field: an input a person types words into, or a text area. */
const TEXT_INPUT = "input:not([type]), input[type='text'], input[type='email'], input[type='password'], input[type='search'], input[type='url'], input[type='tel'], input[type='number'], textarea";

function nameOf(field: Element): string {
  const by = field.getAttribute("aria-labelledby");
  return (by ? document.getElementById(by)?.textContent : field.getAttribute("aria-label") ?? field.closest("label")?.textContent) ?? "(unnamed)";
}

/** Every platform screen's address inside the shell, its params filled, and
 * the sign-in a developer uses; a moved address is a redirect, not a screen. */
const moved = new Set(MOVED.map((each) => each.from));
const SCREENS = [
  ...shellRoutes(SLOT)
    .map((route) => route.path ?? "")
    .filter((path) => path !== "" && !moved.has(path))
    .map((path) => path.replace(/:([A-Za-z]+)/g, (_, name: string) => PARAMS[name] ?? "x")),
  "/login/dev",
];

beforeEach(() => {
  queryClient.clear();
  useSessionStore.getState().setSession("ses_ajax", "ajax");
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.render(null));
  useSessionStore.getState().clear();
});

/** The fields a screen draws once its reads settle and its closed forms are opened. */
async function fieldsOf(address: string): Promise<{ title: string; fields: { name: string; placeholder: string }[] }> {
  // The sign-in is a signed-out person's screen.
  if (address.startsWith("/login")) useSessionStore.getState().clear();
  const router = createMemoryRouter(routes, { initialEntries: [address] });
  await act(async () => root.render(createElement(QueryClientProvider, { client: queryClient }, createElement(RouterProvider, { router }))));
  await settle();
  for (const opens of ["Delete this organization", "Delete my account", "Edit the automation", "Edit the entry"]) {
    const button = [...container.querySelectorAll("button")].find((each) => each.textContent === opens);
    if (button) await act(async () => button.click());
  }
  await settle();
  const title = container.querySelector("h1")?.textContent ?? "";
  const fields = [...container.querySelectorAll(TEXT_INPUT)].map((field) => ({ name: nameOf(field), placeholder: field.getAttribute("placeholder")?.trim() ?? "" }));
  return { title, fields };
}

it("mounts every platform screen, and finds no text field on any without a watermark", async () => {
  const seen = new Map<string, string[]>();
  const bare: string[] = [];
  for (const address of SCREENS) {
    const { title, fields } = await fieldsOf(address);
    expect(title, address).not.toBe("Something went wrong");
    seen.set(address, fields.map((field) => field.name));
    bare.push(...fields.filter((field) => !field.placeholder).map((field) => `${address}: ${field.name}`));
    await act(async () => root.render(null));
    root = createRoot(container);
  }
  expect(bare).toEqual([]);
  // The record forms did open: a screen that drew none would pass for nothing.
  expect(seen.get("/settings/projects")).toEqual(expect.arrayContaining(["Name", "Repository"]));
  expect(seen.get("/settings/projects/p1")).toEqual(expect.arrayContaining(["User", "Password or token"]));
  expect(seen.get("/settings/models")).toEqual(expect.arrayContaining(["New key to Anthropic", "New key to OpenAI"]));
  expect(seen.get("/settings/playbooks")).toEqual(expect.arrayContaining(["Playbook name", "Description", "Steps (Markdown)", "Gates, one a line"]));
  expect(seen.get("/settings/members")).toContain("Invite by email");
  expect(seen.get("/settings/api-keys")).toContain("New key name");
  expect(seen.get("/settings/profile")).toEqual(expect.arrayContaining(["Name", `Type your email, ${user.email}, to confirm`]));
  expect(seen.get("/settings/general")).toContain(`Type the organization's name, ${org.name}, to confirm`);
  expect(seen.get("/automations")).toEqual(expect.arrayContaining(["Name", "Session title", "Brief", "Cost cap a run"]));
  expect(seen.get("/automations/a1")).toContain("Brief");
  expect(seen.get("/knowledge")).toEqual(expect.arrayContaining(["Title", "Recalled by"]));
  expect(seen.get("/knowledge/k1")).toContain("Recalled by");
  expect(seen.get("/")).toContain("Prompt");
  expect(seen.get("/sessions")).toContain("Filter by title");
  expect(seen.get("/sessions/s1")).toContain("Message");
  expect(seen.get("/orgs/new")).toEqual(expect.arrayContaining(["Name"]));
  expect(seen.get("/login/dev")).toEqual(expect.arrayContaining(["Email"]));
}, 60_000);

/** Every screen's source: the features and the app, not the kit's own parts.
 * The tests run in the portal's folder. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const child = join(dir, name);
    if (statSync(child).isDirectory()) return sources(child);
    return name.endsWith(".tsx") ? [child] : [];
  });
}

/** The opening tag that starts at `from`, to its closing ">": an arrow or a
 * comparison inside a {…} value is not its end. */
function openingTag(text: string, from: number): string {
  let depth = 0;
  let quote: string | null = null;
  for (let at = from; at < text.length; at += 1) {
    const char = text[at]!;
    if (quote) {
      if (char === quote) quote = null;
    } else if (char === '"' || char === "'" || char === "`") {
      quote = depth > 0 || char === '"' ? char : null;
    } else if (char === "{") depth += 1;
    else if (char === "}") depth -= 1;
    else if (char === ">" && depth === 0) return text.slice(from, at + 1);
  }
  return text.slice(from);
}

it("draws no text field, in any state of any screen, without a watermark", () => {
  const bare: string[] = [];
  let seen = 0;
  for (const file of [...sources(join(process.cwd(), "src/features")), ...sources(join(process.cwd(), "src/app"))]) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/<(TextField|TextArea|input|textarea)\b/g)) {
      const element = openingTag(text, match.index);
      seen += 1;
      if (/type="(checkbox|radio|hidden|date|file|range|color)"/.test(element)) continue;
      if (!/\bplaceholder=/.test(element)) bare.push(`${file.split("/src/")[1]}: ${element.split("\n")[0]}`);
    }
  }
  expect(seen).toBeGreaterThan(30);
  expect(bare).toEqual([]);
});
