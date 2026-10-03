// Pure: where the keyboard moves in the two overlays, the lightbox and the
// command palette, and the ranking the palette shows its commands in.

/** The item a key moves a lightbox to, or null when the key moves nothing.
 * The arrows wrap around; Home and End go to the first and the last. */
export function lightboxStep(index: number, count: number, key: string): number | null {
  if (count <= 1) return null;
  switch (key) {
    case "ArrowRight":
      return (index + 1) % count;
    case "ArrowLeft":
      return (index - 1 + count) % count;
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return null;
  }
}

/** The command a key moves the palette's choice to; the arrows wrap around. */
export function paletteStep(active: number, count: number, key: string): number | null {
  if (count === 0) return null;
  if (key === "ArrowDown") return (active + 1) % count;
  if (key === "ArrowUp") return (active - 1 + count) % count;
  return null;
}

/** Whether a key press opens the palette: Cmd-K, or Ctrl-K. */
export function opensPalette(event: { key: string; metaKey: boolean; ctrlKey: boolean }): boolean {
  return event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey);
}

function atWordStart(text: string, at: number): boolean {
  return at === 0 || /[\s\-_/.:]/.test(text[at - 1]!);
}

/** How well a label answers a query, higher is better, or null when the
 * query's letters are not all in the label in order. A run of letters
 * scores more than scattered ones, and a match at the start of a word more
 * than one inside it. */
export function matchScore(label: string, query: string): number | null {
  const text = label.toLowerCase();
  const phrase = query.toLowerCase().trim();
  if (phrase === "") return 0;
  // The query whole, as words in the label: above any scattered match, best
  // at the start of a word, and the earlier the better.
  let best: number | null = null;
  for (let at = text.indexOf(phrase); at !== -1; at = text.indexOf(phrase, at + 1)) {
    const score = 1000 - (atWordStart(text, at) ? 0 : 100) - at;
    best = Math.max(best ?? score, score);
  }
  if (best !== null) return best - text.length / 100;
  const wanted = phrase.replace(/\s+/g, "");
  let score = 0;
  let from = 0;
  let previous = -2;
  for (const letter of wanted) {
    const at = text.indexOf(letter, from);
    if (at === -1) return null;
    score += 1;
    if (at === previous + 1) score += 2;
    if (atWordStart(text, at)) score += 3;
    previous = at;
    from = at + 1;
  }
  return score - text.length / 100;
}

export interface Rankable {
  label: string;
  keywords?: readonly string[];
}

/** The commands that answer the query, best first; with no query, every
 * command in the order given. */
export function rankCommands<C extends Rankable>(commands: readonly C[], query: string): C[] {
  if (query.trim() === "") return [...commands];
  return commands
    .map((command, order) => {
      const scores = [command.label, ...(command.keywords ?? [])].map((text) => matchScore(text, query));
      const best = Math.max(...scores.map((score) => score ?? Number.NEGATIVE_INFINITY));
      return { command, order, best };
    })
    .filter((entry) => entry.best !== Number.NEGATIVE_INFINITY)
    .sort((a, b) => b.best - a.best || a.order - b.order)
    .map((entry) => entry.command);
}
