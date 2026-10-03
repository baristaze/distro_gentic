// A command's output, line by line under a gutter of numbers, its standard
// error marked. It follows the end while the reader is at the end, and stays
// where the reader scrolled to otherwise.
import { useLayoutEffect, useRef } from "react";
import { logLines, type LogChunk } from "./logModel";

export function LogView({
  output,
  label,
  limit,
}: {
  output: readonly LogChunk[] | string;
  /** What a screen reader calls the log. */
  label: string;
  limit?: number;
}) {
  const { lines, hidden } = logLines(output, limit);
  const box = useRef<HTMLDivElement>(null);
  const atEnd = useRef(true);
  useLayoutEffect(() => {
    const element = box.current;
    if (element && atEnd.current) element.scrollTop = element.scrollHeight;
  }, [lines.length]);
  const onScroll = () => {
    const element = box.current;
    if (element) atEnd.current = element.scrollHeight - element.scrollTop - element.clientHeight < 8;
  };
  return (
    <div ref={box} className="acme-log" role="log" aria-label={label} tabIndex={0} onScroll={onScroll}>
      {hidden > 0 ? (
        <div className="acme-log-hidden">
          {hidden} earlier {hidden === 1 ? "line" : "lines"} not shown
        </div>
      ) : null}
      {lines.length === 0 ? <div className="acme-log-hidden">No output</div> : null}
      {lines.map((line) => (
        <div key={line.no} className="acme-log-line" data-stream={line.stream}>
          <span className="acme-log-no" aria-hidden="true">
            {line.no}
          </span>
          <span className="acme-log-text">{line.text}</span>
        </div>
      ))}
    </div>
  );
}
