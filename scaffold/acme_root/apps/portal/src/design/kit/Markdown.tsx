// Markdown drawn as elements, never as HTML: what an agent writes cannot
// put a tag or a script on the page. A link opens in a new tab, and a link
// to a path on this site reads as the text it was written as, unless the
// view that draws it hands a `link` of its own.
import { Fragment, type ReactNode } from "react";
import { parseMarkdown, plainText, type Block, type Inline } from "./markdownModel";

/** A link as a view decides it: a web or mail address (`web`), or a path on
 * this site (`path`), with its label drawn and its words. */
export interface MarkdownLink {
  kind: "web" | "path";
  href: string;
  label: ReactNode;
  text: string;
  /** The Markdown it was written as. */
  raw: string;
}

export type LinkView = (link: MarkdownLink) => ReactNode;

const ownLink: LinkView = (link) =>
  link.kind === "web" ? (
    <a href={link.href} target="_blank" rel="noreferrer noopener">
      {link.label}
    </a>
  ) : (
    link.raw
  );

function inline(nodes: readonly Inline[], link: LinkView): ReactNode[] {
  return nodes.map((node, index) => {
    switch (node.kind) {
      case "text":
        return node.text;
      case "code":
        return <code key={index}>{node.text}</code>;
      case "strong":
        return <strong key={index}>{inline(node.children, link)}</strong>;
      case "em":
        return <em key={index}>{inline(node.children, link)}</em>;
      case "link":
      case "path": {
        const text = plainText(node.children);
        const raw = node.kind === "path" ? node.raw : text === node.href ? node.href : `[${text}](${node.href})`;
        const label = inline(node.children, link);
        return <Fragment key={index}>{link({ kind: node.kind === "link" ? "web" : "path", href: node.href, label, text, raw })}</Fragment>;
      }
    }
  });
}

function block(node: Block, index: number, link: LinkView): ReactNode {
  switch (node.kind) {
    case "heading": {
      // A heading inside a page's card sits below the card's own h2.
      const Tag = `h${Math.min(6, node.level + 2)}` as "h3";
      return <Tag key={index}>{inline(node.children, link)}</Tag>;
    }
    case "paragraph":
      return <p key={index}>{inline(node.children, link)}</p>;
    case "code":
      return (
        <pre key={index} className="acme-code" data-lang={node.lang || undefined}>
          <code>{node.text}</code>
        </pre>
      );
    case "list": {
      const items = node.items.map((item, itemIndex) => <li key={itemIndex}>{inline(item, link)}</li>);
      return node.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
    }
    case "quote":
      return <blockquote key={index}>{node.children.map((child, at) => block(child, at, link))}</blockquote>;
    case "table":
      return (
        <table key={index} className="acme-table">
          <thead>
            <tr>
              {node.header.map((cell, cellIndex) => (
                <th key={cellIndex}>{inline(cell, link)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {node.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{inline(cell, link)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    case "rule":
      return <hr key={index} />;
  }
}

export function Markdown({ text, link = ownLink }: { text: string; link?: LinkView }) {
  return <div className="acme-md">{parseMarkdown(text).map((node, index) => block(node, index, link))}</div>;
}
