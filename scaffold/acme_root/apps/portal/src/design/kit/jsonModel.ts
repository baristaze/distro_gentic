// Pure: a JSON value as the rows of a tree a reader folds. A row is a key
// and its value: a leaf shows the value, an object or an array shows how
// much it holds, and its children follow it unless it is folded.

export type JsonKind = "object" | "array" | "string" | "number" | "boolean" | "null";

export interface JsonRow {
  /** Where the value sits: `$`, `$.name`, `$.items[0]`. */
  path: string;
  depth: number;
  key: string | null;
  kind: JsonKind;
  /** A leaf's value as JSON writes it; a container's size in words. */
  text: string;
  /** Whether the row is an object or an array with something in it. */
  folds: boolean;
}

/** The text's value when it is a JSON object or array, else undefined: a
 * bare number or word is not worth a tree. */
export function parseJsonText(text: string): unknown {
  const trimmed = text.trim();
  if (!/^[[{]/.test(trimmed)) return undefined;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return undefined;
  }
}

function kindOf(value: unknown): JsonKind {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  const type = typeof value;
  if (type === "object") return "object";
  if (type === "string" || type === "number" || type === "boolean") return type;
  return "null";
}

function sizeOf(kind: JsonKind, count: number): string {
  if (kind === "array") return `${count} ${count === 1 ? "item" : "items"}`;
  return `${count} ${count === 1 ? "key" : "keys"}`;
}

const IDENT = /^[A-Za-z_$][\w$]*$/;

function childPath(path: string, key: string | number): string {
  if (typeof key === "number") return `${path}[${key}]`;
  return IDENT.test(key) ? `${path}.${key}` : `${path}[${JSON.stringify(key)}]`;
}

export function jsonRows(value: unknown, folded: ReadonlySet<string>): JsonRow[] {
  const rows: JsonRow[] = [];
  const walk = (current: unknown, path: string, depth: number, key: string | null) => {
    const kind = kindOf(current);
    if (kind === "object" || kind === "array") {
      const entries: [string | number, unknown][] = Array.isArray(current)
        ? current.map((item, index) => [index, item])
        : Object.entries(current as Record<string, unknown>);
      rows.push({ path, depth, key, kind, text: sizeOf(kind, entries.length), folds: entries.length > 0 });
      if (folded.has(path)) return;
      for (const [childKey, child] of entries) {
        walk(child, childPath(path, childKey), depth + 1, String(childKey));
      }
      return;
    }
    rows.push({ path, depth, key, kind, text: JSON.stringify(current) ?? "null", folds: false });
  };
  walk(value, "$", 0, null);
  return rows;
}

/** The containers folded at first: every one deeper than `openDepth`. */
export function foldedBelow(value: unknown, openDepth: number): Set<string> {
  return new Set(
    jsonRows(value, new Set())
      .filter((row) => row.folds && row.depth >= openDepth)
      .map((row) => row.path),
  );
}
