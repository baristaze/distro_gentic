// What the record screens' tests share: a fake transport that answers as the
// API does for the signed-in member's org and role, and a page mounted under
// a router and a fresh query cache. Each test file mocks `app/api` with
// `fakeApi(net)` and answers its own routes in `net.answer`; `/v1/me`, the
// members, and the parked sessions the banner reads are answered here.
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { ApiError, type AgentSessionView, type MeView, type Permission, type Role } from "@acme/client";

export type Org = "a" | "b";

export interface Call {
  method: string;
  path: string;
  body?: unknown;
  /** The version a write names as read. */
  ifMatch?: number;
}

export interface Net {
  org: Org;
  role: Role;
  calls: Call[];
  parked: AgentSessionView[];
  answer: (call: Call) => unknown;
}

export const PERMISSIONS: Record<Role, Permission[]> = {
  owner: ["read", "write", "manage_members", "manage_keys"],
  admin: ["read", "write", "manage_members", "manage_keys"],
  member: ["read", "write", "manage_keys"],
  viewer: ["read"],
  service: ["read", "write", "manage_members"],
};

/** One person in each org; each org's records name its own. */
export const PEOPLE = {
  a: { id: "ua", display_name: "Ada", email: "ada@a.test" },
  b: { id: "ub", display_name: "Bea", email: "bea@b.test" },
} as const;

export function newNet(): Net {
  return { org: "a", role: "owner", calls: [], parked: [], answer: (call) => notFound(call.path) };
}

export function notFound(path: string): never {
  throw new ApiError(404, "not_found", `nothing at ${path}`, "req-1");
}

function common(net: Net, call: Call): unknown {
  if (call.method !== "GET") return undefined;
  if (call.path === "/v1/me") {
    return {
      app: "portal",
      role: net.role,
      permissions: PERMISSIONS[net.role],
      user: PEOPLE[net.org],
      org: { id: `org-${net.org}`, name: net.org === "a" ? "Ajax" : "Beta", slug: net.org, kind: "team", created_at: "" },
    } as unknown as MeView;
  }
  if (call.path.startsWith("/v1/users?")) return { items: [PEOPLE[net.org]], next_cursor: null };
  if (call.path.startsWith("/v1/agent-sessions?") && call.path.includes("status=parked")) return { items: net.parked, next_cursor: null };
  return undefined;
}

/** The module `app/api` exports, over `net`: every call is recorded, and
 * each is answered as `net` says, or refused when the answer throws. */
export function fakeApi(net: Net) {
  const send = (method: string, path: string, body?: unknown, options?: { ifMatch?: number }) => {
    const call: Call = body === undefined ? { method, path } : { method, path, body };
    if (options?.ifMatch !== undefined) call.ifMatch = options.ifMatch;
    net.calls.push(call);
    try {
      return Promise.resolve(common(net, call) ?? net.answer(call));
    } catch (caught) {
      return Promise.reject(caught);
    }
  };
  return {
    api: {
      get: (path: string) => send("GET", path),
      post: (path: string, body?: unknown) => send("POST", path, body),
      patch: (path: string, body?: unknown) => send("PATCH", path, body),
      del: (path: string) => send("DELETE", path),
      request: (method: string, path: string, body?: unknown, options?: { ifMatch?: number }) => send(method, path, body, options),
    },
  };
}

let root: Root | null = null;
export const container = typeof document === "undefined" ? (null as unknown as HTMLElement) : document.body.appendChild(document.createElement("div"));

/** The reads settle over a few turns of the event loop. */
export async function settle(): Promise<void> {
  for (let turn = 0; turn < 6; turn += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
}

export async function mount(routes: RouteObject[], address: string) {
  const router = createMemoryRouter(routes, { initialEntries: [address] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client: queryClient }, createElement(RouterProvider, { router }))));
  await settle();
  return router;
}

export async function unmount(): Promise<void> {
  await act(async () => root?.unmount());
  root = null;
}

/** The field whose label says `label`. */
export function field(label: string): HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | undefined {
  const found = [...container.querySelectorAll("label")].find((each) => each.querySelector("span")?.textContent === label);
  return found?.querySelector("input, select, textarea") ?? undefined;
}

/** Types into a field as a person does, so React hears the change. */
export async function enter(label: string, value: string): Promise<void> {
  const input = field(label);
  if (!input) throw new Error(`no field ${label}`);
  const prototype =
    input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(input, value);
  await act(async () => input.dispatchEvent(new Event(input instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })));
}

/** The buttons (and radios) a person can press, by their words. */
export function buttons(): string[] {
  return [...container.querySelectorAll("button")].map((each) => each.textContent ?? "");
}

export async function press(name: string, within: ParentNode = container): Promise<void> {
  const button = [...within.querySelectorAll("button")].find((each) => each.textContent === name);
  if (!button) throw new Error(`no button ${name}`);
  await act(async () => button.click());
  await settle();
}

/** The writes the page sent, in order. */
export function writes(net: Net): Call[] {
  return net.calls.filter((call) => call.method !== "GET");
}
