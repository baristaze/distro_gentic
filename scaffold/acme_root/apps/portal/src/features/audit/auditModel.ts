// Pure: the org's events as the audit lists them: what happened, to which
// record, by whom, and when. An event's kind is `<namespace>.<entity>.<action>`.
// No React, no fetch.
import type { EventView } from "@acme/client";

export interface AuditRow {
  seq: number;
  what: string;
  kind: string;
  targetId: string;
  actorId: string;
  at: string;
}

/** A kind in words: `knowledge.entry.created` is "entry created", in
 * "knowledge". */
export function kindLine(kind: string): { what: string; area: string } {
  const [area = "", ...rest] = kind.split(".");
  if (rest.length === 0) return { what: kind.replace(/_/g, " "), area: "" };
  return { what: rest.join(" ").replace(/_/g, " "), area };
}

export function auditRows(events: readonly EventView[]): AuditRow[] {
  return events.map((event) => ({
    seq: event.seq,
    what: kindLine(event.kind).what,
    kind: event.kind,
    targetId: event.target_id,
    actorId: event.actor_id,
    at: event.produced_at,
  }));
}
