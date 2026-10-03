// Pure: a playbook as its page shows it, and the next version's request
// from a person's form. A playbook's gates are written one to a line, as
// `approve tool <name>` or `deny class <name>`: a gate selects calls by tool
// or by authorization class and needs a person's approval or denies them; it
// never allows. No React, no fetch.
import type { GateBody, PlaybookView, PublishRequest } from "@acme/client";

export const NAME_MAX = 64;
export const DESCRIPTION_MAX = 1024;
export const BODY_MAX = 50_000;

/** A playbook's name as the Agent Skills standard spells it. */
const NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const SELECTOR = /^[a-z][a-z0-9_]{0,63}$/;

export function nameProblem(name: string): string | null {
  if (!name) return "Give the playbook a name.";
  if (name.length > NAME_MAX) return `A name is at most ${NAME_MAX} characters.`;
  if (!NAME.test(name)) return "A name is lowercase words joined by hyphens, such as release-notes.";
  return null;
}

/** The gates a person wrote, one to a line; blank lines are skipped. */
export function gatesOf(text: string): { gates: GateBody[] } | { problem: string } {
  const gates: GateBody[] = [];
  const lines = text.split("\n");
  for (const [index, line] of lines.entries()) {
    const words = line.trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) continue;
    const [decision, by, name] = words;
    const said = `Line ${index + 1} of the gates`;
    if (words.length !== 3 || (decision !== "approve" && decision !== "deny") || (by !== "tool" && by !== "class")) {
      return { problem: `${said} is not a gate: write "approve tool <name>" or "deny class <name>".` };
    }
    if (!SELECTOR.test(name!)) return { problem: `${said} names no ${by}: a name is lowercase letters, digits, and underscores.` };
    gates.push(by === "tool" ? { decision, tool: name! } : { decision, authorization_class: name! });
  }
  return { gates };
}

/** The gates as their lines. */
export function gatesText(gates: readonly Pick<GateBody, "decision" | "tool" | "authorization_class">[]): string {
  return gates.map((gate) => (gate.tool ? `${gate.decision} tool ${gate.tool}` : `${gate.decision} class ${gate.authorization_class ?? ""}`)).join("\n");
}

export interface PlaybookDraft {
  name: string;
  description: string;
  body: string;
  gates: string;
}

export const EMPTY_DRAFT: PlaybookDraft = { name: "", description: "", body: "", gates: "" };

export function publishRequest(draft: PlaybookDraft): { request: PublishRequest } | { problem: string } {
  const name = draft.name.trim();
  const problem = nameProblem(name);
  if (problem) return { problem };
  const description = draft.description.trim();
  if (!description) return { problem: "Say what the playbook is for, and when to use it." };
  if (description.length > DESCRIPTION_MAX) return { problem: `A description is at most ${DESCRIPTION_MAX} characters.` };
  if (!draft.body.trim()) return { problem: "Write the playbook's steps." };
  if (draft.body.length > BODY_MAX) return { problem: `A playbook is at most ${BODY_MAX} characters.` };
  const gates = gatesOf(draft.gates);
  if ("problem" in gates) return gates;
  return { request: { name, description, body: draft.body, gates: gates.gates } };
}

/** The form to publish a name's next version, filled from its latest. */
export function draftOf(playbook: PlaybookView): PlaybookDraft {
  return { name: playbook.name, description: playbook.description, body: playbook.body, gates: gatesText(playbook.gates) };
}

/** What a gate does, in words. */
export function gateLine(gate: Pick<GateBody, "decision" | "tool" | "authorization_class">): string {
  const what = gate.tool ? `a call to ${gate.tool}` : `a call of class ${gate.authorization_class ?? ""}`;
  return gate.decision === "deny" ? `${what} is denied` : `${what} waits for a person's approval`;
}
