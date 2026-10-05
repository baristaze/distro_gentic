// The slot a product fills joins the platform's entries, and refuses an
// entry the two share: a product never shadows a platform screen in silence.
import { expect, it } from "vitest";
import { EMPTY_PRODUCT, joinProducts, routeKey, routePaths, shellRoutes, SlotConflict, type PortalProduct } from "./product";

const page = null;
const platform: PortalProduct = {
  ...EMPTY_PRODUCT,
  routes: [
    { path: "/", element: page },
    { path: "/sessions", element: page },
    { path: "/sessions/:sessionId", element: page },
  ],
  nav: [{ id: "automations", label: "Automations", icon: null, to: "/automations", tip: "" }],
  sessionTabs: [{ id: "step", label: "Step", icon: null, tip: "", offered: () => true, render: () => null }],
  tools: { run_command: { gist: () => "" } },
  settings: [{ group: "Agents", id: "projects", label: "Projects", icon: null, about: "", routes: [{ path: "/projects", element: page }] }],
  agents: [{ kind: "engineer", label: "Engineer", about: "" }],
  examples: { composer: "Describe a task", reply: "Reply", starters: ["one", "two", "three"] },
};
const product = (over: Partial<PortalProduct>): PortalProduct => ({ ...EMPTY_PRODUCT, ...over });
const refusal = (over: Partial<PortalProduct>) => {
  try {
    joinProducts(platform, product(over));
  } catch (caught) {
    expect(caught).toBeInstanceOf(SlotConflict);
    return (caught as Error).message;
  }
  throw new Error("joined");
};

it("joins a product's entries after the platform's, its agents first, its examples in place of the platform's", () => {
  const joined = joinProducts(
    platform,
    product({
      routes: [{ path: "/lines", element: page }],
      nav: [{ id: "lines", label: "Lines", icon: null, to: "/lines", tip: "" }],
      agents: [{ kind: "inspector", label: "Inspector", about: "" }],
      examples: { starters: ["a", "b", "c"] },
    }),
  );
  expect(joined.nav.map((entry) => entry.id)).toEqual(["automations", "lines"]);
  expect(joined.agents.map((agent) => agent.kind)).toEqual(["inspector", "engineer"]);
  expect(joined.examples).toEqual({ composer: "Describe a task", reply: "Reply", starters: ["a", "b", "c"] });
  expect(routePaths(shellRoutes(joined))).toEqual(["/", "/sessions", "/sessions/:", "/lines", "/projects"]);
});

it("joins an empty product to the platform unchanged", () => {
  expect(joinProducts(platform, EMPTY_PRODUCT)).toEqual({ ...platform, routes: platform.routes });
});

it("refuses a product's page at a platform address, whatever its parameter is called", () => {
  expect(refusal({ routes: [{ path: "/sessions", element: page }] })).toContain('address "/sessions"');
  expect(refusal({ routes: [{ path: "/sessions/:id/", element: page }] })).toContain('address "/sessions/:"');
  expect(refusal({ routes: [{ path: "/", children: [{ index: true, element: page }] }] })).toContain('address "/"');
  expect(refusal({ routes: [{ path: "/sessions", children: [{ path: ":anything", element: page }] }] })).toContain("/sessions");
});

it("refuses a product's settings page at a platform address, and a page at a platform setting's", () => {
  expect(
    refusal({ settings: [{ group: "Lab", id: "lab", label: "Lab", icon: null, about: "", routes: [{ path: "/sessions", element: page }] }] }),
  ).toContain('address "/sessions"');
  expect(refusal({ routes: [{ path: "/projects", element: page }] })).toContain('address "/projects"');
});

it("refuses a duplicate id of each kind of entry", () => {
  expect(refusal({ nav: [{ id: "automations", label: "Mine", icon: null, to: "/mine", tip: "" }] })).toContain(
    'left bar entry "automations"',
  );
  expect(refusal({ sessionTabs: [{ id: "step", label: "Step", icon: null, tip: "", offered: () => true, render: () => null }] })).toContain(
    'session tab "step"',
  );
  expect(refusal({ tools: { run_command: { gist: () => "" } } })).toContain('tool "run_command"');
  expect(refusal({ settings: [{ group: "Agents", id: "projects", label: "P", icon: null, about: "", routes: [] }] })).toContain(
    'settings section "projects"',
  );
  expect(refusal({ agents: [{ kind: "engineer", label: "Mine", about: "" }] })).toContain('agent kind "engineer"');
});

it("refuses a duplicate inside the product itself", () => {
  const twice = { id: "lines", label: "Lines", icon: null, to: "/lines", tip: "" };
  expect(refusal({ nav: [twice, twice] })).toContain('left bar entry "lines"');
  expect(refusal({ routes: [{ path: "/lines", element: page }, { path: "lines", element: page }] })).toContain('address "/lines"');
});

it("joins a product's layout with an index page and pages under it", () => {
  const lines = { path: "/lines", element: page, children: [{ index: true, element: page }, { path: ":lineId", element: page }] };
  expect(routePaths(joinProducts(platform, product({ routes: [lines] })).routes)).toContain("/lines/:");
});

it("keys an address by its place", () => {
  expect(routeKey("sessions/:sessionId/")).toBe("/sessions/:");
  expect(routeKey("/")).toBe("/");
});
