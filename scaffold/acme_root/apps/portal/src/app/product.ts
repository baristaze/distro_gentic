// The slot a product fills: its pages, its entries in the left bar, its tabs
// and tool cards in a session, its settings, its agents, and its examples.
// The platform's own entries (`platform.tsx`) have the same shape, and the
// product's (`../product.tsx`) join them here, so a product adds a screen
// without editing a platform file. Two entries with one id, one kind, one
// tool, or one address are refused at start: a product never shadows a
// platform screen in silence.
import type { ReactNode } from "react";
import type { RouteObject } from "react-router-dom";
import type { AgentSessionView } from "@acme/client";
import type { Call } from "../features/session/timelineModel";

/** A session as a product's tab or tool card sees it. */
export interface SlotSession {
  session: AgentSessionView;
  /** Its steps paired into tool calls, each with what it was asked and
   * what it answered. */
  calls: readonly Call[];
  /** Whether a run holds its loop now, or is about to take it. */
  running: boolean;
  /** Shows one of the session's tabs. */
  open: (tabId: string) => void;
}

/** An entry in the left bar, under New session. */
export interface NavEntry {
  id: string;
  label: string;
  icon: ReactNode;
  to: string;
  /** What the entry's tooltip says. */
  tip: string;
  /** A hook: the number drawn beside the label, or null for none. Called on
   * every render of its entry, as any hook is. */
  count?: () => number | null;
}

/** A tab of a session's right pane. */
export interface SessionTab {
  id: string;
  label: string;
  icon: ReactNode;
  tip: string;
  /** Whether this session has anything for the tab. */
  offered: (s: SlotSession) => boolean;
  /** Whether the tab opens by itself now. It does so once a session, the
   * first time this holds, and a person who closes it keeps it closed. */
  opensItself?: (s: SlotSession) => boolean;
  render: (s: SlotSession) => ReactNode;
}

/** How a tool's call reads in a session. */
export interface ToolView {
  /** One line: what it was asked and what it answered. */
  gist: (input: unknown, output: unknown) => string;
  /** A card in the timeline, in place of the line. */
  card?: (s: SlotSession, call: Call) => ReactNode;
  /** The tab a click on the call opens. */
  tab?: string;
}

/** A section of Settings, with the pages it holds; the first route is its address. */
export interface SettingsEntry {
  group: string;
  id: string;
  label: string;
  icon: ReactNode;
  about: string;
  routes: RouteObject[];
}

/** An agent a person may start a session on. There is no route that lists
 * the kinds, so the slot names them. */
export interface AgentChoice {
  kind: string;
  label: string;
  about: string;
}

/** The examples the fields show while empty, and Home's starter prompts. */
export interface Examples {
  composer?: string;
  reply?: string;
  starters?: readonly string[];
}

export interface PortalProduct {
  routes: RouteObject[];
  nav: NavEntry[];
  sessionTabs: SessionTab[];
  tools: Record<string, ToolView>;
  settings: SettingsEntry[];
  /** The first is the composer's default. */
  agents: AgentChoice[];
  examples: Examples;
}

/** An empty slot: what a product that adds nothing passes. */
export const EMPTY_PRODUCT: PortalProduct = {
  routes: [],
  nav: [],
  sessionTabs: [],
  tools: {},
  settings: [],
  agents: [],
  examples: {},
};

export class SlotConflict extends Error {
  override name = "SlotConflict";
}

/** An address as the router matches it: one leading slash, none trailing,
 * and a parameter by its place, not its name, so `/a/:id` and `/a/:key`
 * are one address. */
export function routeKey(path: string): string {
  const parts = path.split("/").filter((part) => part !== "");
  return `/${parts.map((part) => (part.startsWith(":") ? ":" : part)).join("/")}`;
}

/** Every address a list of routes serves, a child's under its parent's. A
 * route with no path (a layout, an index) serves its parent's address and
 * adds none of its own. */
export function routePaths(routes: readonly RouteObject[], base = ""): string[] {
  return routes.flatMap((route) => {
    const own = route.path === undefined ? base : route.path.startsWith("/") ? route.path : `${base}/${route.path}`;
    const children = route.children ? routePaths(route.children, own) : [];
    return route.path === undefined ? children : [routeKey(own), ...children];
  });
}

function refuseTwice(what: string, values: readonly string[]): void {
  const seen = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) throw new SlotConflict(`Two entries of the portal share the ${what} "${value}".`);
    seen.add(value);
  }
}

function addresses(product: PortalProduct): string[] {
  return [...routePaths(product.routes), ...product.settings.flatMap((entry) => routePaths(entry.routes))];
}

/** The platform's entries and a product's as one slot: the platform's first,
 * but for the agents, where the product's first is the default, and the
 * examples, where the product's replace the platform's. A duplicate is a
 * SlotConflict. */
export function joinProducts(platform: PortalProduct, product: PortalProduct): PortalProduct {
  refuseTwice("address", [...addresses(platform), ...addresses(product)]);
  refuseTwice("left bar entry", [...platform.nav, ...product.nav].map((entry) => entry.id));
  refuseTwice("session tab", [...platform.sessionTabs, ...product.sessionTabs].map((tab) => tab.id));
  refuseTwice("tool", [...Object.keys(platform.tools), ...Object.keys(product.tools)]);
  refuseTwice("settings section", [...platform.settings, ...product.settings].map((entry) => entry.id));
  refuseTwice("agent kind", [...product.agents, ...platform.agents].map((agent) => agent.kind));
  return {
    routes: [...platform.routes, ...product.routes],
    nav: [...platform.nav, ...product.nav],
    sessionTabs: [...platform.sessionTabs, ...product.sessionTabs],
    tools: { ...platform.tools, ...product.tools },
    settings: [...platform.settings, ...product.settings],
    agents: [...product.agents, ...platform.agents],
    examples: {
      composer: product.examples.composer ?? platform.examples.composer,
      reply: product.examples.reply ?? platform.examples.reply,
      starters: product.examples.starters ?? platform.examples.starters,
    },
  };
}

/** Every route the shell serves: the pages, then the settings' pages. */
export function shellRoutes(slot: PortalProduct): RouteObject[] {
  return [...slot.routes, ...slot.settings.flatMap((entry) => entry.routes)];
}
