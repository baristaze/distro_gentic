import type { FindingView } from "@acme/client";
import { Muted } from "../../design/kit";
import { tokens } from "../../design/tokens";
import { findingLines, NOT_CHECKED } from "./findingsModel";

/** What the lever checks found in a version: advice for the person who
 * published it, which never refused the publish. A version they never read,
 * one published before they ran, says so, never that they found nothing. */
export function Findings({ findings }: { findings: readonly FindingView[] | null }) {
  if (findings === null) return <Muted style={{ fontSize: tokens.font.size.sm }}>{NOT_CHECKED}</Muted>;
  if (findings.length === 0) return <Muted style={{ fontSize: tokens.font.size.sm }}>The checks found nothing to read again.</Muted>;
  return (
    <div data-findings>
      <Muted style={{ fontSize: tokens.font.size.sm }}>
        What the checks found, to read again before an agent follows it. A finding advises; this version stands.
      </Muted>
      <ul aria-label="What the checks found" style={{ margin: 0 }}>
        {findingLines(findings).map((line, index) => (
          <li key={index}>
            <strong>{line.label}</strong>: {line.detail}
            {line.excerpt ? <Muted> “{line.excerpt}”</Muted> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
