// Markdown drawn as elements, never as HTML: what an agent writes cannot
// put a tag or a script on the page. A link opens in a new tab.
import type { ReactNode } from "react";
import { parseMarkdown, type Block, type Inline } from "./markdownModel";

function inline(nodes: readonly Inline[]): ReactNode[] {
  return nodes.map((node, index) => {
    switch (node.kind) {
      case "text":
        return node.text;
      case "code":
        return <code key={index}>{node.text}</code>;
      case "strong":
        return <strong key={index}>{inline(node.children)}</strong>;
      case "em":
        return <em key={index}>{inline(node.children)}</em>;
      case "link":
        return (
          <a key={index} href={node.href} target="_blank" rel="noreferrer noopener">
            {inline(node.children)}
          </a>
        );
    }
  });
}

function block(node: Block, index: number): ReactNode {
  switch (node.kind) {
    case "heading": {
      // A heading inside a page's card sits below the card's own h2.
      const Tag = `h${Math.min(6, node.level + 2)}` as "h3";
      return <Tag key={index}>{inline(node.children)}</Tag>;
    }
    case "paragraph":
      return <p key={index}>{inline(node.children)}</p>;
    case "code":
      return (
        <pre key={index} className="acme-code" data-lang={node.lang || undefined}>
          <code>{node.text}</code>
        </pre>
      );
    case "list": {
      const items = node.items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>);
      return node.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
    }
    case "quote":
      return <blockquote key={index}>{node.children.map(block)}</blockquote>;
    case "table":
      return (
        <table key={index} className="acme-table">
          <thead>
            <tr>
              {node.header.map((cell, cellIndex) => (
                <th key={cellIndex}>{inline(cell)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {node.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{inline(cell)}</td>
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

export function Markdown({ text }: { text: string }) {
  return <div className="acme-md">{parseMarkdown(text).map(block)}</div>;
}
