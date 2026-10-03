// A unified diff, file by file: each line numbered before and after, an
// added line marked + and a removed one -, so the change reads without colour.
import { diffFileName, wholeDiff } from "./diffModel";

const SIGN = { add: "+", del: "-", context: " " } as const;

export function DiffView({ text }: { text: string }) {
  // A text with a line no hunk holds is drawn whole, so no line is lost.
  const files = wholeDiff(text);
  if (files === null) return <pre className="acme-code">{text}</pre>;
  return (
    <div className="acme-diff">
      {files.map((file, fileIndex) => (
        <section key={fileIndex} className="acme-diff-file" aria-label={diffFileName(file)}>
          <header className="acme-diff-head">
            <span className="acme-diff-path">{diffFileName(file)}</span>
            <span className="acme-diff-count" data-kind="add">
              +{file.added}
            </span>
            <span className="acme-diff-count" data-kind="del">
              -{file.removed}
            </span>
          </header>
          <table className="acme-diff-lines">
            {file.hunks.map((hunk, hunkIndex) => (
              <tbody key={hunkIndex}>
                <tr data-kind="hunk">
                  <td colSpan={4}>{hunk.header}</td>
                </tr>
                {hunk.lines.map((line, lineIndex) => (
                  <tr key={lineIndex} data-kind={line.kind}>
                    <td className="acme-diff-no">{line.oldNo ?? ""}</td>
                    <td className="acme-diff-no">{line.newNo ?? ""}</td>
                    <td className="acme-diff-sign" aria-hidden="true">
                      {SIGN[line.kind]}
                    </td>
                    <td className="acme-diff-text">{line.text}</td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </section>
      ))}
    </div>
  );
}
