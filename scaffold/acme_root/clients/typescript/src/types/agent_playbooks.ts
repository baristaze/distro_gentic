// The agent_playbooks namespace's types: what an org's sessions follow, and its pins. An app names each
// as agent_playbooks.<Name>, through the package's entry.
import type { components } from "../schema/agent_playbooks";

type Schemas = components["schemas"];

export type AgentPlaybookView = Schemas["AgentPlaybookView"];
export type GateBody = Schemas["GateBody"];
export type InvocationView = Schemas["InvocationView"];
export type InvokeRequest = Schemas["InvokeRequest"];
export type PinRequest = Schemas["PinRequest"];
export type PinView = Schemas["PinView"];
export type PublishRequest = Schemas["PublishRequest"];
