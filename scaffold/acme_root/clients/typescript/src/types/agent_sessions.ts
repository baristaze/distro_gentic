// The agent_sessions namespace's types: sessions with an agent: started, spoken to, steered, and read. An app names each
// as agent_sessions.<Name>, through the package's entry.
import type { components } from "../schema/agent_sessions";

type Schemas = components["schemas"];

export type AgentSessionControl = Schemas["AgentSessionControl"];
export type AgentSessionPageView = Schemas["AgentSessionPageView"];
export type AgentSessionStatus = Schemas["AgentSessionStatus"];
export type AgentSessionView = Schemas["AgentSessionView"];
export type AgentStepPageView = Schemas["AgentStepPageView"];
export type AgentStepView = Schemas["AgentStepView"];
export type Among = Schemas["Among"];
export type ApprovalPageView = Schemas["ApprovalPageView"];
export type ApprovalView = Schemas["ApprovalView"];
export type BoundsView = Schemas["BoundsView"];
export type ControlRequest = Schemas["ControlRequest"];
export type DecisionRequest = Schemas["DecisionRequest"];
export type MessageRequest = Schemas["MessageRequest"];
export type ParkView = Schemas["ParkView"];
export type PrincipalRequest = Schemas["PrincipalRequest"];
export type AgentSessionModelUsageView = Schemas["AgentSessionModelUsageView"];
export type StartAgentSessionRequest = Schemas["StartAgentSessionRequest"];
export type ToolCallPageView = Schemas["ToolCallPageView"];
export type ToolCallView = Schemas["ToolCallView"];
export type ToolUseView = Schemas["ToolUseView"];
export type UnlockView = Schemas["UnlockView"];
export type VisibilityRequest = Schemas["VisibilityRequest"];
export type StartQuestionRequest = Schemas["StartQuestionRequest"];
export type QuestionRequest = Schemas["QuestionRequest"];

// A question's stream, as server-sent events (`POST /v1/agent-sessions/questions`
// and `POST /v1/agent-sessions/{id}/questions`): its schema names the events
// in its description alone, so their data is written here as the API sends it.

/** The first event: the session the question asks, and the question as stored. */
export interface QuestionSessionEvent {
  agent_session_id: string;
  agent_step_id: string;
  seq: number;
}

/** A piece of the text the model writes, the step it adds up to, its place
 * in that step's stream, and its text block. The model's text: render it as
 * text, never as markup. */
export interface QuestionTextEvent {
  agent_step_id: string;
  n: number;
  index: number;
  text: string;
}

/** The last event: how the run stopped, the loop's outcome and its cause,
 * and the steps from the question to the run's last. */
export interface QuestionEndEvent {
  agent_session_id: string;
  loop_id: string | null;
  end: "ended" | "parked" | "yielded" | "stale" | "idle";
  outcome: Schemas["LoopOutcome"] | null;
  cause: string | null;
  first_seq: number;
  last_seq: number;
}

/** The last event of a stream whose run failed, in place of its end. */
export interface QuestionErrorEvent {
  code: string;
  message: string;
}
