// The agent_steps namespace's types: a session's history, as its steps. An app names each
// as agent_steps.<Name>, through the package's entry.
import type { components } from "../schema/agent_steps";

type Schemas = components["schemas"];

export type AgentStepType = Schemas["AgentStepType"];
export type ParkReason = Schemas["ParkReason"];
