// Pure: what Home's composer starts. The prompt's first line is the
// session's title, cut at 80 characters, and the whole prompt is its first
// message; the agent and the agent project come from the chips. No React, no fetch.
import type { AgentProjectView, StartSessionRequest } from "@acme/client";
import type { AgentChoice } from "../../app/product";
import { startRequest } from "../sessions/sessionsModel";

export const TITLE_CUT = 80;

/** The title a prompt gives its session: its first line that holds words,
 * cut at 80 characters with an ellipsis. */
export function titleFromPrompt(prompt: string): string {
  const line =
    prompt
      .split("\n")
      .map((text) => text.trim())
      .find((text) => text !== "") ?? "";
  if (line.length <= TITLE_CUT) return line;
  return `${line.slice(0, TITLE_CUT - 1).trimEnd()}…`;
}

export interface ComposerDraft {
  prompt: string;
  kind: string;
  /** The agent project it starts in; empty for none. */
  agentProjectId: string;
}

/** The session a draft starts and the message it sends, or why it may not start yet. */
export function composerStart(
  draft: ComposerDraft,
  agentProject: { required: boolean; count: number },
): { request: StartSessionRequest; text: string } | { problem: string } {
  const text = draft.prompt.trim();
  if (!text) return { problem: "Describe the task first." };
  if (!draft.kind.trim()) return { problem: "Choose the agent that works on it." };
  const made = startRequest({ title: titleFromPrompt(text), kind: draft.kind, agentProjectId: draft.agentProjectId }, agentProject);
  return "problem" in made ? made : { request: made.request, text };
}

/** The agent the chip shows: the one chosen, else the slot's first. */
export function chosenAgent(agents: readonly AgentChoice[], kind: string | null): AgentChoice | null {
  return agents.find((agent) => agent.kind === kind) ?? agents[0] ?? null;
}

/** The agent project the chip shows: the one chosen, else the first where a
 * an agent project is required, else none. Null agent projects are not read yet. */
export function chosenAgentProject(
  agentProjects: readonly Pick<AgentProjectView, "id" | "name">[] | null,
  required: boolean,
  id: string | null,
): Pick<AgentProjectView, "id" | "name"> | null {
  const list = agentProjects ?? [];
  if (id !== null) return list.find((agentProject) => agentProject.id === id) ?? null;
  return required ? (list[0] ?? null) : null;
}
