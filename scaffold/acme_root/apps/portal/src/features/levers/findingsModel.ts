// Pure: what the lever checks found in an agent playbook version or an agent knowledge
// entry, as its page shows it. A finding advises: the version stands as it
// was published. No React, no fetch.
import type { FindingView, LeverCheck } from "@acme/client";

/** What each check looks for, in words. */
export const CHECK_LABEL: Record<LeverCheck, string> = {
  repeated_phrase: "A phrase said again and again",
  contradiction: "A must and a must-not on one subject",
  unknown_name: "A name no kind holds",
  unbounded_retry: "A retry with no stopping condition",
  past_session_bound: "Longer than a session holds whole",
};

/** What a version the checks never read says: one published before they
 * ran is not checked, which is not checked and clean. */
export const NOT_CHECKED = "The checks have not read this version: it was published before they ran.";

export interface FindingLine {
  label: string;
  detail: string;
  excerpt: string | null;
}

/** The findings as lines, in the order the checks answered them. */
export function findingLines(findings: readonly FindingView[]): FindingLine[] {
  return findings.map((finding) => ({ label: CHECK_LABEL[finding.check], detail: finding.detail, excerpt: finding.excerpt ?? null }));
}
