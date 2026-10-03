// @vitest-environment jsdom
// A unified diff reads into files, hunks, and lines numbered before and
// after; a removed line that starts with "--" stays a line of its hunk.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { DiffView } from "./DiffView";
import { diffFileName, looksLikeDiff, parseUnifiedDiff } from "./diffModel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const TWO_FILES = [
  "diff --git a/app.py b/app.py",
  "index 1111111..2222222 100644",
  "--- a/app.py",
  "+++ b/app.py",
  "@@ -1,3 +1,3 @@",
  " def main():",
  "--- a comment that was a rule",
  "+    return 1",
  "     pass",
  "diff --git a/old.txt b/new.txt",
  "--- a/old.txt",
  "+++ b/new.txt",
  "@@ -4 +4,2 @@",
  "-four",
  "+four",
  "+five",
  "\\ No newline at end of file",
].join("\n");

/** What `git show` prints: the commit and its message above the diff. */
const GIT_SHOW = [
  "commit 0123456789abcdef0123456789abcdef01234567",
  "Author: A Person <a@example.test>",
  "Date:   Sat Oct 3 10:00:00 2026 +0000",
  "",
  "    Tidy the readme",
  "",
  "diff --git a/README.md b/README.md",
  "index 1111111..2222222 100644",
  "--- a/README.md",
  "+++ b/README.md",
  "@@ -1 +1 @@",
  "-old",
  "+new",
  "",
].join("\n");

const PROSE_THEN_HUNK = ["I changed one line:", "@@ -1 +1 @@", "-old", "+new", "and the tests pass."].join("\n");

describe("parseUnifiedDiff", () => {
  it("reads each file with its paths, its hunks, and its counts", () => {
    const files = parseUnifiedDiff(TWO_FILES);
    expect(files.map((file) => [diffFileName(file), file.added, file.removed])).toEqual([
      ["app.py", 1, 1],
      ["old.txt → new.txt", 2, 1],
    ]);
  });

  it("numbers each line before and after, and keeps a removed '--' line in its hunk", () => {
    const [first] = parseUnifiedDiff(TWO_FILES);
    expect(first!.hunks[0]!.lines).toEqual([
      { kind: "context", text: "def main():", oldNo: 1, newNo: 1 },
      { kind: "del", text: "-- a comment that was a rule", oldNo: 2, newNo: null },
      { kind: "add", text: "    return 1", oldNo: null, newNo: 2 },
      { kind: "context", text: "    pass", oldNo: 3, newNo: 3 },
    ]);
  });

  it("reads a new file and a deleted one as having no path on one side", () => {
    const created = parseUnifiedDiff("--- /dev/null\n+++ b/new.md\n@@ -0,0 +1 @@\n+hello");
    expect([created[0]!.oldPath, created[0]!.newPath]).toEqual([null, "new.md"]);
  });

  it("tells a diff from prose that mentions one", () => {
    expect(looksLikeDiff(TWO_FILES)).toBe(true);
    expect(looksLikeDiff(`${TWO_FILES}\n\n`)).toBe(true);
    expect(looksLikeDiff("I changed two files and ran the tests.")).toBe(false);
  });

  it("is a diff only when every line belongs to a hunk or a file's header", () => {
    expect(looksLikeDiff(GIT_SHOW)).toBe(false);
    expect(looksLikeDiff(PROSE_THEN_HUNK)).toBe(false);
    expect(looksLikeDiff("diff --git a/a.png b/a.png\nBinary files a/a.png and b/a.png differ\n@@ -1 +1 @@\n-x\n+y")).toBe(false);
    expect(looksLikeDiff("diff --git a/a b/b\nsimilarity index 100%\nrename from a\nrename to b\n" + TWO_FILES)).toBe(false);
  });
});

describe("DiffView", () => {
  it("draws each line with its numbers and its sign", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => root.render(createElement(DiffView, { text: TWO_FILES })));
    const rows = [...container.querySelectorAll("tr[data-kind='add']")].map((row) => row.textContent);
    expect(rows[0]).toBe("2+    return 1");
    expect(container.querySelectorAll("section.acme-diff-file")).toHaveLength(2);
    await act(async () => root.render(createElement(DiffView, { text: "not a diff" })));
    expect(container.querySelector("pre")!.textContent).toBe("not a diff");
    await act(async () => root.unmount());
  });

  it("draws a git show and a prose-then-hunk output whole, every line kept", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    for (const text of [GIT_SHOW, PROSE_THEN_HUNK]) {
      await act(async () => root.render(createElement(DiffView, { text })));
      expect(container.querySelector("section.acme-diff-file")).toBeNull();
      expect(container.querySelector("pre")!.textContent).toBe(text);
    }
    await act(async () => root.unmount());
  });
});
