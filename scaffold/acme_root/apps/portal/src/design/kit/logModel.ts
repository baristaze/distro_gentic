// Pure: a command's output as numbered lines. The terminal's colour and
// cursor codes are dropped, a line a carriage return rewrote shows what it
// showed last, a line split across two chunks of one stream is joined, and
// only the tail is kept when the output is long.

export type LogStream = "stdout" | "stderr";

export interface LogChunk {
  stream: LogStream;
  text: string;
}

export interface LogLine {
  no: number;
  stream: LogStream;
  text: string;
}

export interface LogLines {
  lines: LogLine[];
  /** How many lines before the first one kept were dropped. */
  hidden: number;
}

const ESC = String.fromCharCode(27);
const BEL = String.fromCharCode(7);
// A control sequence (ESC [ ... final byte) or an operating-system command
// (ESC ] ... BEL or ESC \): what a terminal draws with, never what it says.
const CODES = new RegExp(`${ESC}\\[[0-9;?]*[ -/]*[@-~]|${ESC}\\][^${BEL}${ESC}]*(?:${BEL}|${ESC}\\\\)`, "g");

export function stripAnsi(text: string): string {
  return text.replace(CODES, "");
}

/** What a line shows once its carriage returns have done their work. */
function shown(line: string): string {
  const trimmed = line.endsWith("\r") ? line.slice(0, -1) : line;
  const at = trimmed.lastIndexOf("\r");
  return at === -1 ? trimmed : trimmed.slice(at + 1);
}

export const LOG_LINE_LIMIT = 2000;

export function logLines(chunks: readonly LogChunk[] | string, limit = LOG_LINE_LIMIT): LogLines {
  const list: readonly LogChunk[] = typeof chunks === "string" ? [{ stream: "stdout", text: chunks }] : chunks;
  const done: { stream: LogStream; text: string }[] = [];
  let open: { stream: LogStream; text: string } | null = null;
  for (const chunk of list) {
    const pieces = stripAnsi(chunk.text).split("\n");
    pieces.forEach((piece, index) => {
      const last = index === pieces.length - 1;
      if (open !== null && open.stream !== chunk.stream) {
        done.push(open);
        open = null;
      }
      const text: string = (open?.text ?? "") + piece;
      if (last) {
        open = text === "" ? null : { stream: chunk.stream, text };
      } else {
        done.push({ stream: chunk.stream, text });
        open = null;
      }
    });
  }
  if (open !== null) done.push(open);
  const all = done.map((line, index) => ({ no: index + 1, stream: line.stream, text: shown(line.text) }));
  const hidden = Math.max(0, all.length - limit);
  return { lines: all.slice(hidden), hidden };
}
