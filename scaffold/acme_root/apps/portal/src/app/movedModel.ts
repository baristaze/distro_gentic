// Pure: where an address the portal moved lands now. A bookmark to an old
// address still opens the screen it became, with its parameters, its query,
// and its anchor kept. No React.

/** The new address, its parameters filled in from the old one's, and the old
 * address's query and anchor kept after any query the new one names. */
export function movedTo(to: string, params: Readonly<Record<string, string | undefined>>, search: string, hash: string): string {
  const [path = "", query = ""] = to.split("?");
  const filled = path
    .split("/")
    .map((part) => (part.startsWith(":") ? encodeURIComponent(params[part.slice(1)] ?? "") : part))
    .join("/");
  const joined = new URLSearchParams(query);
  new URLSearchParams(search).forEach((value, key) => {
    if (!joined.has(key)) joined.append(key, value);
  });
  const kept = joined.toString();
  return `${filled}${kept ? `?${kept}` : ""}${hash}`;
}
