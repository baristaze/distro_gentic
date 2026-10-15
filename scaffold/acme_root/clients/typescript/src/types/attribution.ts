// The attribution namespace's types: who sees what a session did. An app names each
// as attribution.<Name>, through the package's entry.
import type { components } from "../schema/attribution";

type Schemas = components["schemas"];

export type Visibility = Schemas["Visibility"];
