// A JSON value as a tree: an object or an array folds under its key, and
// what is deeper than `openDepth` starts folded, so a large answer opens on
// its outline.
import { useState } from "react";
import { foldedBelow, jsonRows } from "./jsonModel";

export function JsonView({ value, label, openDepth = 2 }: { value: unknown; label: string; openDepth?: number }) {
  const [folded, setFolded] = useState(() => foldedBelow(value, openDepth));
  const toggle = (path: string) =>
    setFolded((current) => {
      const next = new Set(current);
      if (!next.delete(path)) next.add(path);
      return next;
    });
  return (
    <div className="acme-json" role="tree" aria-label={label}>
      {jsonRows(value, folded).map((row) => (
        <div
          key={row.path}
          role="treeitem"
          aria-level={row.depth + 1}
          aria-expanded={row.folds ? !folded.has(row.path) : undefined}
          className="acme-json-row"
          style={{ paddingLeft: `${row.depth * 16}px` }}
        >
          {row.folds ? (
            <button type="button" className="acme-json-toggle" aria-label={`${folded.has(row.path) ? "Unfold" : "Fold"} ${row.path}`} onClick={() => toggle(row.path)}>
              {folded.has(row.path) ? "▸" : "▾"}
            </button>
          ) : (
            <span className="acme-json-toggle" aria-hidden="true" />
          )}
          {row.key !== null ? <span className="acme-json-key">{row.key}: </span> : null}
          <span className="acme-json-value" data-kind={row.kind}>
            {row.kind === "object" ? `{${row.text}}` : row.kind === "array" ? `[${row.text}]` : row.text}
          </span>
        </div>
      ))}
    </div>
  );
}
