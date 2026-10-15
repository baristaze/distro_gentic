// The matrix namespace's types: the model matrix's fills and what a tenant on its own keys may choose. An app names each
// as matrix.<Name>, through the package's entry.
import type { components } from "../schema/matrix";

type Schemas = components["schemas"];

export type FillChoiceView = Schemas["FillChoiceView"];
export type FillOptionsView = Schemas["FillOptionsView"];
export type FillView = Schemas["FillView"];
export type ProviderName = Schemas["ProviderName"];
