import { expect, it } from "vitest";
import { approvalRows } from "./approvalsModel";

it("lists the held calls oldest first, one per session and step", () => {
  const rows = approvalRows([
    { session_id: "s2", seq: 4, requested_at: "2026-10-03T10:05:00Z", tool: "git_push", authorization_class: "write", principal_id: "u1" },
    { session_id: "s1", seq: 9, requested_at: "2026-10-03T10:01:00Z", tool: "shell", authorization_class: "exec", principal_id: "u2" },
  ]);
  expect(rows.map((row) => [row.key, row.tool])).toEqual([
    ["s1:9", "shell"],
    ["s2:4", "git_push"],
  ]);
});
