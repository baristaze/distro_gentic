// Pure: how each of the platform's tools reads in one line of a session's
// timeline, from what it was asked and what it answered. The platform's
// part of the slot (`platform.tsx`) carries these, as a product's part
// carries its own tools' lines. No React.
import { parseJsonText } from "../../design/kit";
import { counts, oneLine, type Gist } from "./timelineModel";

const asked = (input: unknown, name: string): string | null => {
  if (!input || typeof input !== "object") return null;
  const value = (input as Record<string, unknown>)[name];
  return typeof value === "string" ? value : null;
};

/** A command's words as a shell shows them, a word with a blank or a quote
 * in single quotes. */
export function commandLine(argv: unknown): string {
  if (!Array.isArray(argv)) return "";
  return argv.map((word) => (typeof word === "string" && /^[\w./:=@%+,-]+$/.test(word) ? word : `'${String(word).replace(/'/g, "'\\''")}'`)).join(" ");
}

function exitCode(output: unknown): number | null {
  const answer = typeof output === "string" ? parseJsonText(output) : undefined;
  if (!answer || typeof answer !== "object") return null;
  const code = (answer as Record<string, unknown>)["exit_code"];
  return typeof code === "number" ? code : null;
}

const quoted = (text: string | null) => (text ? `“${oneLine(text, 60)}”` : "");

/** The verb of a call that answered, or, while no answer has come (it waits
 * for a decision, or runs), of what it asks: a held command has not run. */
const verb = (output: unknown, done: string, asks: string) => (output === null || output === undefined ? asks : done);

export const PLATFORM_GISTS: Readonly<Record<string, Gist>> = {
  list_files: (input, output) => `${verb(output, "Listed", "List")} ${asked(input, "path") ?? "."}`,
  read_file: (input) => `Read ${asked(input, "path") ?? "a file"}`,
  search_code: (input, output) => {
    const path = asked(input, "path");
    return `${verb(output, "Searched", "Search")} for ${quoted(asked(input, "pattern"))}${path && path !== "." ? ` in ${path}` : ""}`;
  },
  write_file: (input, output) => `${verb(output, "Wrote", "Write")} ${asked(input, "path") ?? "a file"} ${counts("", asked(input, "text") ?? "")}`,
  edit_file: (input, output) => `${verb(output, "Edited", "Edit")} ${asked(input, "path") ?? "a file"} ${counts(asked(input, "old_text") ?? "", asked(input, "new_text") ?? "")}`,
  run_command: (input, output) => {
    const code = exitCode(output);
    const line = commandLine((input as Record<string, unknown> | null)?.["argv"]);
    const exit = code !== null && code !== 0 ? ` · exit ${code}` : "";
    return `${verb(output, "Ran", "Run")} ${line ? `\`${oneLine(line, 80)}\`` : "a command"}${exit}`;
  },
  search_knowledge: (input, output) => `${verb(output, "Searched", "Search")} knowledge for ${quoted(asked(input, "query"))}`.trim(),
  read_knowledge: () => "Read a knowledge entry",
  suggest_knowledge: (input, output) => `${verb(output, "Suggested", "Suggest")} a knowledge entry ${quoted(asked(input, "title"))}`.trim(),
  validate: (_input, output) => `${verb(output, "Validated", "Validate")} the head`,
  open_pull_request: (input, output) => `${verb(output, "Opened", "Open")} a pull request ${quoted(asked(input, "title"))}`.trim(),
  submit_result: (input, output) => `${verb(output, "Submitted", "Submit")} its result: ${asked(input, "claim") ?? "a claim"}`,
  write_plan: (_input, output) => `${verb(output, "Wrote", "Write")} a plan`,
  ask_person: (input, output) => `${verb(output, "Asked", "Ask")} ${quoted(asked(input, "question"))}`.trim(),
  hand_off_to_engineer: (input, output) => `${verb(output, "Handed", "Hand")} off ${quoted(asked(input, "title"))}`.trim(),
};
