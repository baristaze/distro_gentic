// The levers namespace's types: what an org's sessions reached, and how often each stalled. An app names each
// as levers.<Name>, through the package's entry.
import type { components } from "../schema/levers";

type Schemas = components["schemas"];

export type FindingView = Schemas["FindingView"];
export type LeverCheck = Schemas["LeverCheck"];
