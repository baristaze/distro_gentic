// The agent_automations namespace's types: an org's agent automations. An app names each
// as agent_automations.<Name>, through the package's entry.
import type { components } from "../schema/agent_automations";

type Schemas = components["schemas"];

export type AgentAutomationPrincipalView = Schemas["AgentAutomationPrincipalView"];
export type AgentAutomationRequest = Schemas["AgentAutomationRequest"];
export type AgentAutomationView = Schemas["AgentAutomationView"];
