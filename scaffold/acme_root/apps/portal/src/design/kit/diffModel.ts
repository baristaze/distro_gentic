// Pure: a unified diff read into files, hunks, and numbered lines. A hunk's
// header says how many lines it holds, so a removed line that begins with
// "--" is read as a line of the hunk, never as the next file's header.

export type DiffLineKind = "add" | "del" | "context";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
  /** The line's number before the change; null for an added line. */
  oldNo: number | null;
  /** The line's number after the change; null for a removed line. */
  newNo: number | null;
}

export interface DiffHunk {
  header: string;
  lines: DiffLine[];
}

export interface DiffFile {
  /** Null when the file is new. */
  oldPath: string | null;
  /** Null when the file is deleted. */
  newPath: string | null;
  hunks: DiffHunk[];
  added: number;
  removed: number;
}

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/;
const GIT_HEADER = /^diff --git a\/(.+) b\/(.+)$/;

/** A path from a `---` or `+++` line: its `a/` or `b/` dropped, a trailing
 * timestamp dropped, and `/dev/null` read as no file. */
function pathOf(field: string): string | null {
  const path = field.split("\t")[0]!.trim();
  if (path === "/dev/null") return null;
  return path.replace(/^[ab]\//, "");
}

function newFile(): DiffFile {
  return { oldPath: null, newPath: null, hunks: [], added: 0, removed: 0 };
}

/** The lines git writes between a file's `diff --git` line and its hunks. */
const EXTENDED_HEADER =
  /^(index |old mode |new mode |new file mode |deleted file mode |similarity index |dissimilarity index |rename from |rename to |copy from |copy to )/;

/** The files a text holds, and how many of its lines no file draws: a line
 * outside every hunk and every file header, or the header of a file with no
 * hunk. Blank lines at the text's end are none of them. */
function readDiff(text: string): { files: DiffFile[]; stray: number } {
  const files: DiffFile[] = [];
  const headerLines = new Map<DiffFile, number>();
  let file: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldNo = 0;
  let newNo = 0;
  let oldLeft = 0;
  let newLeft = 0;
  let stray = 0;
  const start = (): DiffFile => {
    file = newFile();
    files.push(file);
    hunk = null;
    return file;
  };
  const header = (owner: DiffFile) => headerLines.set(owner, (headerLines.get(owner) ?? 0) + 1);
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let last = lines.length - 1;
  while (last >= 0 && lines[last] === "") last -= 1;
  lines.forEach((line, index) => {
    if (hunk !== null && file !== null && (oldLeft > 0 || newLeft > 0)) {
      const current: DiffHunk = hunk;
      const owner: DiffFile = file;
      if (line.startsWith("+")) {
        current.lines.push({ kind: "add", text: line.slice(1), oldNo: null, newNo: newNo++ });
        owner.added += 1;
        newLeft -= 1;
        return;
      }
      if (line.startsWith("-")) {
        current.lines.push({ kind: "del", text: line.slice(1), oldNo: oldNo++, newNo: null });
        owner.removed += 1;
        oldLeft -= 1;
        return;
      }
      if (line.startsWith(" ") || line === "") {
        current.lines.push({ kind: "context", text: line.slice(1), oldNo: oldNo++, newNo: newNo++ });
        oldLeft -= 1;
        newLeft -= 1;
        return;
      }
      if (!line.startsWith("\\")) {
        hunk = null;
        oldLeft = 0;
        newLeft = 0;
      }
    }
    // "\ No newline at end of file" says something of the line before it.
    if (line.startsWith("\\") && hunk !== null) return;
    const git = GIT_HEADER.exec(line);
    if (git) {
      const started = start();
      started.oldPath = git[1]!;
      started.newPath = git[2]!;
      header(started);
      return;
    }
    if (line.startsWith("--- ")) {
      const owner: DiffFile = file === null || (file as DiffFile).hunks.length > 0 ? start() : file;
      owner.oldPath = pathOf(line.slice(4));
      header(owner);
      return;
    }
    if (line.startsWith("+++ ") && file !== null) {
      (file as DiffFile).newPath = pathOf(line.slice(4));
      header(file);
      return;
    }
    if (file !== null && (file as DiffFile).hunks.length === 0 && EXTENDED_HEADER.test(line)) {
      header(file);
      return;
    }
    const found = HUNK.exec(line);
    if (found) {
      const owner: DiffFile = file ?? start();
      hunk = { header: line, lines: [] };
      owner.hunks.push(hunk);
      oldNo = Number(found[1]);
      newNo = Number(found[3]);
      oldLeft = found[2] === undefined ? 1 : Number(found[2]);
      newLeft = found[4] === undefined ? 1 : Number(found[4]);
      return;
    }
    if (index <= last) stray += 1;
  });
  for (const each of files) if (each.hunks.length === 0) stray += headerLines.get(each) ?? 0;
  return { files: files.filter((each) => each.hunks.length > 0), stray };
}

export function parseUnifiedDiff(text: string): DiffFile[] {
  return readDiff(text).files;
}

/** The files of a text that is a unified diff and nothing else, or null.
 * Every line must be a file's header, a hunk's header, or a line a hunk
 * counts: a commit's message above its diff, or prose before a hunk, makes
 * the text something else, which is drawn whole rather than as its hunks. */
export function wholeDiff(text: string): DiffFile[] | null {
  if (!/^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@/m.test(text)) return null;
  const { files, stray } = readDiff(text);
  if (stray > 0 || !files.some((file) => file.hunks.some((hunk) => hunk.lines.length > 0))) return null;
  return files;
}

/** Whether a text reads as a unified diff and nothing else (`wholeDiff`). */
export function looksLikeDiff(text: string): boolean {
  return wholeDiff(text) !== null;
}

/** "a.py", or "a.py → b.py" for a rename. */
export function diffFileName(file: DiffFile): string {
  if (file.oldPath && file.newPath && file.oldPath !== file.newPath) return `${file.oldPath} → ${file.newPath}`;
  return file.newPath ?? file.oldPath ?? "";
}
