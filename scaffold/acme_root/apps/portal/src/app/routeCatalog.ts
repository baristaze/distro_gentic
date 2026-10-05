// Pure: the route catalog, every address the shell serves with the line it
// says of itself and what each parameter names, read off the same routes
// the router serves: the platform's and the product's pages, then their
// settings. `docs/portal-routes.md` is its Markdown, in the support
// assistant's corpus, so the assistant links only to pages that exist. No
// React, no fetch.
import type { RouteObject } from "react-router-dom";
import type { PortalProduct, RouteAbout } from "./product";

export interface CatalogRoute {
  path: string;
  about: string;
  params: readonly { name: string; about: string }[];
}

/** A route's own line, or null when it says none. */
export function aboutOf(route: RouteObject): RouteAbout | null {
  const handle = route.handle as Partial<RouteAbout> | undefined;
  return typeof handle?.about === "string" && handle.about.trim() !== "" ? (handle as RouteAbout) : null;
}

/** The names of an address's parameters, in their order. */
export function paramNames(path: string): string[] {
  return path.split("/").flatMap((part) => (part.startsWith(":") ? [part.slice(1).replace(/\?$/, "")] : []));
}

function rows(routes: readonly RouteObject[], fallback: (route: RouteObject) => string | null, base = ""): CatalogRoute[] {
  return routes.flatMap((route) => {
    const path = route.path === undefined ? base : route.path.startsWith("/") ? route.path : `${base}/${route.path}`;
    const children = route.children ? rows(route.children, fallback, path) : [];
    if (route.path === undefined) return children;
    const own = aboutOf(route);
    const about = own?.about ?? fallback(route) ?? "";
    const params = paramNames(path).map((name) => ({ name, about: own?.params?.[name] ?? "" }));
    return [{ path, about, params }, ...children];
  });
}

/** Every address the shell serves, in the router's order. A settings
 * section's first page says the section's own line where it says none. A
 * row with an empty line or an empty parameter is one the catalog cannot
 * explain; the catalog's test refuses it. */
export function routeCatalog(slot: PortalProduct): CatalogRoute[] {
  return [
    ...rows(slot.routes, () => null),
    ...slot.settings.flatMap((entry) => rows(entry.routes, (route) => (route === entry.routes[0] ? `Settings › ${entry.label}: ${entry.about}` : null))),
  ];
}

const cell = (text: string) => text.replace(/\|/g, "\\|").replace(/\s+/g, " ").trim();

/** The catalog as the corpus document reads it. */
export function catalogMarkdown(routes: readonly CatalogRoute[]): string {
  const lines = [
    "# The portal's pages",
    "",
    "<!-- Generated from the portal's route catalog (apps/portal/src/app/routeCatalog.ts);",
    "     its test fails while this file differs, and `vitest run -u` writes it again. -->",
    "",
    "Every page of the portal, by its address, with what it shows. Link a",
    "page with a Markdown link whose target is its address, each `:name`",
    "filled in as its line says: `/sessions/<id>` for one session. In the",
    "support dock, a link to one of these addresses opens its page beside the",
    "conversation; any other link shows as text.",
    "",
    "A message sent from the dock ends with a `page` block: the address the",
    "person is on, the route it matched, and the parameters it named, as data.",
    "",
    "| Address | What it shows | Parameters |",
    "| --- | --- | --- |",
    ...routes.map((route) => {
      const params = route.params.map((param) => `\`${param.name}\`: ${cell(param.about)}`).join("; ");
      return `| \`${route.path}\` | ${cell(route.about)} | ${params} |`;
    }),
    "",
  ];
  return lines.join("\n");
}
