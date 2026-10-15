// The agent_projects namespace's types: an org's agent projects and their repositories' fetch credentials. An app names each
// as agent_projects.<Name>, through the package's entry.
import type { components } from "../schema/agent_projects";

type Schemas = components["schemas"];

export type AgentProjectView = Schemas["AgentProjectView"];
export type CreateAgentProjectRequest = Schemas["CreateAgentProjectRequest"];
export type FetchCredentialRequest = Schemas["FetchCredentialRequest"];
export type FetchCredentialView = Schemas["FetchCredentialView"];
export type RepositoryView = Schemas["RepositoryView"];
