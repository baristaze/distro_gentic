// The spend_budgets namespace's types: what an org's sessions spent against their budgets. An app names each
// as spend_budgets.<Name>, through the package's entry.
import type { components } from "../schema/spend_budgets";

type Schemas = components["schemas"];

export type BudgetUsageView = Schemas["BudgetUsageView"];
export type UsagePageView = Schemas["UsagePageView"];
