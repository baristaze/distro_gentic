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
export type QuestionView = Schemas["QuestionView"];
export type SessionModelUsageView = Schemas["SessionModelUsageView"];
export type StartAgentSessionRequest = Schemas["StartAgentSessionRequest"];
export type ToolCallPageView = Schemas["ToolCallPageView"];
export type ToolCallView = Schemas["ToolCallView"];
export type ToolUseView = Schemas["ToolUseView"];
export type VisibilityRequest = Schemas["VisibilityRequest"];
