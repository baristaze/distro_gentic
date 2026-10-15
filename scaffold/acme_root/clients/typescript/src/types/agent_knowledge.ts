// The agent_knowledge namespace's types: what an org's sessions recall. An app names each
// as agent_knowledge.<Name>, through the package's entry.
import type { components } from "../schema/agent_knowledge";

type Schemas = components["schemas"];

export type AgentKnowledgeRequest = Schemas["AgentKnowledgeRequest"];
export type AgentKnowledgeStatus = Schemas["AgentKnowledgeStatus"];
export type AgentKnowledgeView = Schemas["AgentKnowledgeView"];
