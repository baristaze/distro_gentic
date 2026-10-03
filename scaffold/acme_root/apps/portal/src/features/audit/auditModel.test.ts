import { expect, it } from "vitest";
import { auditRows, kindLine } from "./auditModel";

it("says a kind in words, with its area", () => {
  expect(kindLine("knowledge.entry.created")).toEqual({ what: "entry created", area: "knowledge" });
  expect(kindLine("tenancy.api_key.revoked")).toEqual({ what: "api key revoked", area: "tenancy" });
  expect(kindLine("heartbeat")).toEqual({ what: "heartbeat", area: "" });
});

it("keeps the stream's order", () => {
  const rows = auditRows([
    { seq: 1, kind: "projects.project.created", target_id: "p1", produced_at: "2026-10-03T10:00:00Z", actor_id: "u1" },
    { seq: 2, kind: "projects.project.updated", target_id: "p1", produced_at: "2026-10-03T10:01:00Z", actor_id: "u1" },
  ]);
  expect(rows.map((row) => [row.seq, row.what])).toEqual([
    [1, "project created"],
    [2, "project updated"],
  ]);
});
