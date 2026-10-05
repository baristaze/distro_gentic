// The route catalog lists every address the shell serves, a product's
// included, each with its line and a line for each parameter, and the
// support assistant's corpus document is that catalog as it is now: a page
// the router serves and the document does not list is a link the
// assistant cannot know.
import { describe, expect, it, vi } from "vitest";
import { PRODUCT } from "../product";
import { PLATFORM } from "./platform";
import { EMPTY_PRODUCT, joinProducts, routeKey, routePaths, shellRoutes, type PortalProduct } from "./product";
import { catalogMarkdown, paramNames, routeCatalog } from "./routeCatalog";

// The pages are read, never drawn: no call leaves.
vi.mock("./api", () => ({ api: {} }));
vi.mock("./config", () => ({ runtimeConfig: () => ({ environment: "local", devSignIn: true }) }));

const SLOT = joinProducts(PLATFORM, PRODUCT);

describe("the route catalog", () => {
  it("lists every address the shell registers, once, in the router's order", () => {
    expect(routeCatalog(SLOT).map((route) => routeKey(route.path))).toEqual(routePaths(shellRoutes(SLOT)));
  });

  it("says a line for every page and every parameter it takes", () => {
    const unexplained = routeCatalog(SLOT).flatMap((route) => [
      ...(route.about.trim() ? [] : [route.path]),
      ...route.params.filter((param) => !param.about.trim()).map((param) => `${route.path} :${param.name}`),
    ]);
    expect(unexplained).toEqual([]);
  });

  it("lists a product's pages and settings beside the platform's", () => {
    const product: PortalProduct = {
      ...EMPTY_PRODUCT,
      routes: [{ path: "/boards/:boardId", handle: { about: "One board", params: { boardId: "the board's id" } } }],
      settings: [{ group: "Product", id: "boards", label: "Boards", icon: null, about: "Each board's owners", routes: [{ path: "/settings/boards" }] }],
    };
    const listed = routeCatalog(joinProducts(PLATFORM, product));
    expect(listed).toContainEqual({ path: "/boards/:boardId", about: "One board", params: [{ name: "boardId", about: "the board's id" }] });
    // A section's first page says the section's own line.
    expect(listed).toContainEqual({ path: "/settings/boards", about: "Settings › Boards: Each board's owners", params: [] });
  });

  it("refuses a page that says nothing, or leaves a parameter unexplained", () => {
    const product: PortalProduct = { ...EMPTY_PRODUCT, routes: [{ path: "/quiet" }, { path: "/boards/:boardId", handle: { about: "One board" } }] };
    const listed = routeCatalog(joinProducts(PLATFORM, product));
    expect(listed.find((route) => route.path === "/quiet")?.about).toBe("");
    expect(listed.find((route) => route.path === "/boards/:boardId")?.params).toEqual([{ name: "boardId", about: "" }]);
  });

  it("reads a parameter's name off its address", () => {
    expect(paramNames("/settings/projects/:projectId")).toEqual(["projectId"]);
    expect(paramNames("/a/:one/b/:two?")).toEqual(["one", "two"]);
    expect(paramNames("/")).toEqual([]);
  });

  it("escapes a cell's bar, so a line never breaks the table", () => {
    const text = catalogMarkdown([{ path: "/a", about: "this | that", params: [] }]);
    expect(text).toContain("| `/a` | this \\| that |  |");
  });

  it("is the support assistant's corpus document, as the routes are now", async () => {
    await expect(catalogMarkdown(routeCatalog(SLOT))).toMatchFileSnapshot("../../../../docs/portal-routes.md");
  });
});
