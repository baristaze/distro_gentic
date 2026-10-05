// Pure: what a support reply's links become, and the page each message is
// sent from. A link to an address on this site that the router serves
// becomes a chip, which opens its page in the main area; any other link,
// to another site or to an address no route serves, is plain text with its
// address shown, so a model's link can never be a chip that leaves the
// site. The page rides at the end of each message as data: one line of JSON
// in a fenced `page` block, never words of the person's. No React, no fetch.
import { matchRoutes, type RouteObject } from "react-router-dom";
import { aboutOf } from "../routeCatalog";

/** A link as the dock draws it: a chip to a page, or text. */
export type SupportLink = { kind: "chip"; to: string; label: string } | { kind: "text"; text: string };

/** The origin an address is read against: one no address can name. */
const HERE = "https://portal.invalid";

/** The address on this site that `href` names, normalised (`..` resolved,
 * its query and fragment kept), or null for anything that could leave it:
 * another scheme, another host, or a path that starts `//` or `/\`. */
export function sitePath(href: string): string | null {
  const trimmed = href.trim();
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || trimmed.startsWith("/\\")) return null;
  let url: URL;
  try {
    url = new URL(trimmed, HERE);
  } catch {
    return null;
  }
  if (url.origin !== HERE) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Whether a route of `routes` serves the path, its query and fragment aside. */
export function served(path: string, routes: readonly RouteObject[]): boolean {
  const pathname = path.split(/[?#]/, 1)[0]!;
  return (matchRoutes([...routes], pathname) ?? []).some((match) => match.route.path !== undefined);
}

/** A reply's link as the dock draws it: a chip when the router serves its
 * address, else its words and its address as text. */
export function supportLink(href: string, label: string, routes: readonly RouteObject[]): SupportLink {
  const path = sitePath(href);
  if (path !== null && served(path, routes)) return { kind: "chip", to: path, label: label.trim() || path };
  const words = label.trim();
  return { kind: "text", text: !words || words === href ? href : `${words} (${href})` };
}

/** The page a message is sent from, as the message carries it. */
export interface PageContext {
  /** The address, with its query. */
  path: string;
  /** The route that serves it, `:name` for each parameter; null when none does. */
  route: string | null;
  /** The route's own line, from the catalog. */
  page: string | null;
  /** What each parameter names, such as the session the page shows. */
  params: Readonly<Record<string, string>>;
}

/** The longest any value of the page runs: an address is the person's, but
 * one a link wrote can be anything. */
export const PAGE_VALUE_MAX = 200;

const clip = (value: string) => (value.length > PAGE_VALUE_MAX ? `${value.slice(0, PAGE_VALUE_MAX)}…` : value);

export function pageContext(pathname: string, search: string, routes: readonly RouteObject[]): PageContext {
  const matches = (matchRoutes([...routes], pathname) ?? []).filter((match) => match.route.path !== undefined);
  const last = matches[matches.length - 1];
  const params = Object.fromEntries(
    Object.entries(last?.params ?? {}).flatMap(([name, value]) => (value === undefined ? [] : [[clip(name), clip(value)]])),
  );
  return {
    path: clip(`${pathname}${search}`),
    route: last?.route.path ?? null,
    page: last ? (aboutOf(last.route)?.about ?? null) : null,
    params,
  };
}

const OPEN = "~~~page";
const CLOSE = "~~~";

/** The message as it is sent: the person's words, then the page as data. */
export function withPage(text: string, page: PageContext): string {
  return `${text}\n\n${OPEN}\n${JSON.stringify(page)}\n${CLOSE}`;
}

const TRAILER = /\n\n~~~page\n(.*)\n~~~\s*$/;

/** A message as a timeline shows it: the person's words, and the page it
 * was sent from when it ends with one. A block that does not read as a
 * page stays in the words. */
export function splitPage(text: string): { text: string; page: PageContext | null } {
  const found = TRAILER.exec(text);
  if (!found) return { text, page: null };
  let read: unknown;
  try {
    read = JSON.parse(found[1]!);
  } catch {
    return { text, page: null };
  }
  const page = read as Partial<PageContext> | null;
  if (typeof page !== "object" || page === null || typeof page.path !== "string") return { text, page: null };
  return {
    text: text.slice(0, found.index),
    page: {
      path: page.path,
      route: typeof page.route === "string" ? page.route : null,
      page: typeof page.page === "string" ? page.page : null,
      params: typeof page.params === "object" && page.params !== null ? (page.params as Record<string, string>) : {},
    },
  };
}
