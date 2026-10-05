// Pure: the Markdown an agent writes, read into blocks and inline runs that
// a component draws as elements. Nothing here becomes HTML: a tag in the
// text stays text, and a link goes only where `safeHref` lets it. A link to
// a path on this site is kept apart, as a `path`, which draws as its text
// unless the view that draws it decides otherwise.

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "link"; href: string; children: Inline[] }
  /** `[label](/a/path)`: a link to an address on this site, and the text it was written as. */
  | { kind: "path"; href: string; children: Inline[]; raw: string };

export type Block =
  | { kind: "heading"; level: number; children: Inline[] }
  | { kind: "paragraph"; children: Inline[] }
  | { kind: "code"; lang: string; text: string }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "quote"; children: Block[] }
  | { kind: "table"; header: Inline[][]; rows: Inline[][][] }
  | { kind: "rule" };

/** A link's target when it is a web address or a mail address, else null:
 * a `javascript:` or a `data:` target is never a link. */
export function safeHref(href: string): string | null {
  const trimmed = href.trim();
  return /^(https?:\/\/|mailto:)/i.test(trimmed) ? trimmed : null;
}

const INLINE = /`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*|__(.+?)__|\*([^*\s](?:[^*]*[^*\s])?)\*|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g;

export function parseInline(text: string): Inline[] {
  const out: Inline[] = [];
  const push = (node: Inline) => {
    const last = out[out.length - 1];
    if (node.kind === "text" && last?.kind === "text") last.text += node.text;
    else out.push(node);
  };
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    const index = match.index;
    if (index > at) push({ kind: "text", text: text.slice(at, index) });
    const [whole, code, label, href, strong, strongToo, em, bare] = match;
    if (code !== undefined) push({ kind: "code", text: code });
    else if (label !== undefined && href !== undefined) {
      const target = safeHref(href);
      if (target) push({ kind: "link", href: target, children: parseInline(label) });
      else if (href.startsWith("/")) push({ kind: "path", href, children: parseInline(label), raw: whole });
      else push({ kind: "text", text: whole });
    } else if (strong !== undefined || strongToo !== undefined) {
      push({ kind: "strong", children: parseInline(strong ?? strongToo!) });
    } else if (em !== undefined) push({ kind: "em", children: parseInline(em) });
    else if (bare !== undefined) push({ kind: "link", href: bare, children: [{ kind: "text", text: bare }] });
    at = index + whole.length;
  }
  if (at < text.length) push({ kind: "text", text: text.slice(at) });
  return out;
}

/** The words of inline runs, without their marks. */
export function plainText(nodes: readonly Inline[]): string {
  return nodes.map((node) => ("children" in node ? plainText(node.children) : node.text)).join("");
}

const FENCE = /^\s*(```|~~~)\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const ITEM = /^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function startsBlock(line: string, next: string | undefined): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    ITEM.test(line) ||
    QUOTE.test(line) ||
    (line.includes("|") && next !== undefined && TABLE_RULE.test(next))
  );
}

export function parseMarkdown(text: string): Block[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (line.trim() === "") {
      i += 1;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i]!.trim().startsWith(fence[1]!)) body.push(lines[i++]!);
      i += 1;
      blocks.push({ kind: "code", lang: fence[2] ?? "", text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1]!.length, children: parseInline(heading[2]!) });
      i += 1;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ kind: "rule" });
      i += 1;
      continue;
    }
    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i]!)) body.push(QUOTE.exec(lines[i++]!)![1]!);
      blocks.push({ kind: "quote", children: parseMarkdown(body.join("\n")) });
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]!)) {
      const header = cells(line).map(parseInline);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && lines[i]!.includes("|") && lines[i]!.trim() !== "") {
        rows.push(cells(lines[i++]!).map(parseInline));
      }
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    const item = ITEM.exec(line);
    if (item) {
      const ordered = item[2] !== undefined;
      const items: string[] = [];
      while (i < lines.length) {
        const current = lines[i]!;
        const next = ITEM.exec(current);
        if (next && (next[2] !== undefined) === ordered) {
          items.push(next[3]!);
          i += 1;
        } else if (items.length > 0 && /^\s{2,}\S/.test(current)) {
          items[items.length - 1] += ` ${current.trim()}`;
          i += 1;
        } else break;
      }
      blocks.push({ kind: "list", ordered, items: items.map(parseInline) });
      continue;
    }
    const body: string[] = [];
    while (i < lines.length && lines[i]!.trim() !== "" && (body.length === 0 || !startsBlock(lines[i]!, lines[i + 1]))) {
      body.push(lines[i++]!.trim());
    }
    blocks.push({ kind: "paragraph", children: parseInline(body.join(" ")) });
  }
  return blocks;
}
