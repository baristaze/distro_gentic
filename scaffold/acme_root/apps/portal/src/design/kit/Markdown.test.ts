// @vitest-environment jsdom
// What an agent writes, drawn as elements: a tag stays text, and a link goes
// only to a web or a mail address.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { Markdown } from "./Markdown";
import { parseInline, parseMarkdown, safeHref } from "./markdownModel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

describe("parseMarkdown", () => {
  it("reads headings, paragraphs, lists, code, quotes, tables, and rules", () => {
    const blocks = parseMarkdown(
      ["# Done", "", "Two lines", "of one paragraph.", "", "- one", "- two", "", "```py", "x = 1", "```", "> said", "", "| a | b |", "|---|---|", "| 1 | 2 |", "", "---"].join("\n"),
    );
    expect(blocks.map((block) => block.kind)).toEqual(["heading", "paragraph", "list", "code", "quote", "table", "rule"]);
    expect(blocks[1]).toEqual({ kind: "paragraph", children: [{ kind: "text", text: "Two lines of one paragraph." }] });
    expect(blocks[3]).toEqual({ kind: "code", lang: "py", text: "x = 1" });
  });

  it("reads code, strong, emphasis, and links inside a line", () => {
    expect(parseInline("run `make check`, **all** of it, *now*, see [docs](https://example.test/a)")).toEqual([
      { kind: "text", text: "run " },
      { kind: "code", text: "make check" },
      { kind: "text", text: ", " },
      { kind: "strong", children: [{ kind: "text", text: "all" }] },
      { kind: "text", text: " of it, " },
      { kind: "em", children: [{ kind: "text", text: "now" }] },
      { kind: "text", text: ", see " },
      { kind: "link", href: "https://example.test/a", children: [{ kind: "text", text: "docs" }] },
    ]);
  });

  it("lets a link go only to a web or a mail address", () => {
    expect([safeHref("https://a.test"), safeHref("mailto:a@b.test"), safeHref("javascript:alert(1)"), safeHref("data:text/html,x")]).toEqual([
      "https://a.test",
      "mailto:a@b.test",
      null,
      null,
    ]);
  });
});

describe("Markdown", () => {
  it("draws a tag as text and a script link as words", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () =>
      root.render(createElement(Markdown, { text: "<script>alert(1)</script> and [click](javascript:alert(1)) and [ok](https://example.test)" })),
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    const links = [...container.querySelectorAll("a")];
    expect(links.map((link) => [link.textContent, link.getAttribute("href"), link.getAttribute("rel")])).toEqual([
      ["ok", "https://example.test", "noreferrer noopener"],
    ]);
    await act(async () => root.unmount());
  });
});
