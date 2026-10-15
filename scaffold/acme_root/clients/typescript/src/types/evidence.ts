// The evidence namespace's types: what a session ran and what it produced. An app names each
// as evidence.<Name>, through the package's entry.
import type { components } from "../schema/evidence";

type Schemas = components["schemas"];

export type ExecutionPageView = Schemas["ExecutionPageView"];
export type ExecutionView = Schemas["ExecutionView"];
export type ValidationView = Schemas["ValidationView"];
export type WorkProductView = Schemas["WorkProductView"];
