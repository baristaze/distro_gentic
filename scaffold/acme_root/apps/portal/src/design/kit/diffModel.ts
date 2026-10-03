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

export function parseUnifiedDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldNo = 0;
  let newNo = 0;
  let oldLeft = 0;
  let newLeft = 0;
  const start = (): DiffFile => {
    file = newFile();
    files.push(file);
    hunk = null;
    return file;
  };
  for (const line of text.replace(/\r\n/g, "\n").split("\n")) {
    if (hunk !== null && file !== null && (oldLeft > 0 || newLeft > 0)) {
      const current: DiffHunk = hunk;
      const owner: DiffFile = file;
      if (line.startsWith("+")) {
        current.lines.push({ kind: "add", text: line.slice(1), oldNo: null, newNo: newNo++ });
        owner.added += 1;
        newLeft -= 1;
        continue;
      }
      if (line.startsWith("-")) {
        current.lines.push({ kind: "del", text: line.slice(1), oldNo: oldNo++, newNo: null });
        owner.removed += 1;
        oldLeft -= 1;
        continue;
      }
      if (line.startsWith(" ") || line === "") {
        current.lines.push({ kind: "context", text: line.slice(1), oldNo: oldNo++, newNo: newNo++ });
        oldLeft -= 1;
        newLeft -= 1;
        continue;
      }
      if (!line.startsWith("\\")) {
        hunk = null;
        oldLeft = 0;
        newLeft = 0;
      }
    }
    // "\ No newline at end of file" says something of the line before it.
    if (line.startsWith("\\")) continue;
    const git = GIT_HEADER.exec(line);
    if (git) {
      const started = start();
      started.oldPath = git[1]!;
      started.newPath = git[2]!;
      continue;
    }
    if (line.startsWith("--- ")) {
      const owner: DiffFile = file === null || (file as DiffFile).hunks.length > 0 ? start() : file;
      owner.oldPath = pathOf(line.slice(4));
      continue;
    }
    if (line.startsWith("+++ ") && file !== null) {
      (file as DiffFile).newPath = pathOf(line.slice(4));
      continue;
    }
    const header = HUNK.exec(line);
    if (header) {
      const owner: DiffFile = file ?? start();
      hunk = { header: line, lines: [] };
      owner.hunks.push(hunk);
      oldNo = Number(header[1]);
      newNo = Number(header[3]);
      oldLeft = header[2] === undefined ? 1 : Number(header[2]);
      newLeft = header[4] === undefined ? 1 : Number(header[4]);
    }
  }
  return files.filter((each) => each.hunks.length > 0);
}

/** Whether a text reads as a unified diff: at least one hunk with a line. */
export function looksLikeDiff(text: string): boolean {
  if (!/^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@/m.test(text)) return false;
  return parseUnifiedDiff(text).some((file) => file.hunks.some((hunk) => hunk.lines.length > 0));
}

/** "a.py", or "a.py → b.py" for a rename. */
export function diffFileName(file: DiffFile): string {
  if (file.oldPath && file.newPath && file.oldPath !== file.newPath) return `${file.oldPath} → ${file.newPath}`;
  return file.newPath ?? file.oldPath ?? "";
}
