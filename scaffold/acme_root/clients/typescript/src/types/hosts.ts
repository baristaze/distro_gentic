// The hosts namespace's types: an org's pools, the claimants enrolled in each, and the tokens
// that enroll them. An app names each as hosts.<Name>, through the package's entry.
import type { components } from "../schema/hosts";

type Schemas = components["schemas"];

export type PoolView = Schemas["PoolView"];
export type CreatePoolRequest = Schemas["CreatePoolRequest"];
export type ClaimantView = Schemas["ClaimantView"];
export type EnrollmentTokenView = Schemas["EnrollmentTokenView"];
export type IssueEnrollmentTokenRequest = Schemas["IssueEnrollmentTokenRequest"];
export type IssuedEnrollmentTokenView = Schemas["IssuedEnrollmentTokenView"];
