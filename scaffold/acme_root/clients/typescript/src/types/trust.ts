// The trust namespace's types: an org's own keys to its model providers. An app names each
// as trust.<Name>, through the package's entry.
import type { components } from "../schema/trust";

type Schemas = components["schemas"];

export type ProviderKeyView = Schemas["ProviderKeyView"];
