// The dock continues a conversation only when it is the person's own, of the
// support assistant, and neither archived nor deleted; each person keeps
// their own in each org. The answer joins its stream's pieces as they come,
// and a park ends it with its cause.
import { expect, it } from "vitest";
import { continues, conversationKey, endLine, failedLine, heard, isSupport, SUPPORT_KIND } from "./supportModel";

const mine = { kind: SUPPORT_KIND, created_by: "u1", archived_at: null, deleted_at: null };

it("continues the person's own conversation with the support assistant", () => {
  expect(continues(mine, "u1")).toBe(true);
});

it("never continues another member's, another kind's, an archived or a deleted session, or one before the person is known", () => {
  expect(continues({ ...mine, created_by: "u2" }, "u1")).toBe(false);
  expect(continues({ ...mine, kind: "platform_assistant" }, "u1")).toBe(false);
  expect(continues({ ...mine, archived_at: "2026-10-05T10:00:00Z" }, "u1")).toBe(false);
  expect(continues({ ...mine, deleted_at: "2026-10-05T10:00:00Z" }, "u1")).toBe(false);
  expect(continues(mine, null)).toBe(false);
  expect(continues(undefined, "u1")).toBe(false);
});

it("keeps one conversation per org and person", () => {
  expect(conversationKey("o1", "u1")).toBe("o1/u1");
  expect(conversationKey("o2", "u1")).not.toBe(conversationKey("o1", "u1"));
  expect(conversationKey(null, "u1")).toBeNull();
  expect(conversationKey("o1", null)).toBeNull();
});

it("knows a support conversation by its kind alone", () => {
  expect(isSupport({ kind: SUPPORT_KIND, title: "anything" })).toBe(true);
  expect(isSupport({ kind: "platform_assistant", title: "Support" })).toBe(false);
});

it("joins the answer's pieces to the step each adds up to, in the order they come", () => {
  const first = heard([], { agent_step_id: "s1", n: 0, index: 0, text: "It waits " });
  const second = heard(first, { agent_step_id: "s1", n: 1, index: 0, text: "on a host." });
  const next = heard(second, { agent_step_id: "s2", n: 0, index: 0, text: "Then" });
  expect(first[0]!.runs[0]!.text).toBe("It waits ");
  expect(second).toHaveLength(1);
  expect(second[0]).toMatchObject({ stepId: "s1", last: 1, runs: [{ kind: "text", text: "It waits on a host." }] });
  expect(next.map((stream) => stream.stepId)).toEqual(["s1", "s2"]);
});

it("says nothing of a whole answer, and why one stopped short", () => {
  const end = { agent_session_id: "a", loop_id: "l", end: "ended", outcome: "succeeded", cause: null, first_seq: 3, last_seq: 6 } as const;
  expect(endLine(end)).toBeNull();
  const parked = { ...end, outcome: "inconclusive", cause: "a request waits for nothing: the loop parks on budget (spend_budget)" } as const;
  expect(endLine(parked)).toBe("Stopped: a request waits for nothing: the loop parks on budget (spend_budget).");
  expect(endLine({ ...end, end: "stale", outcome: null })).toBe("Stopped: a later question took this conversation over.");
  expect(endLine({ ...end, outcome: "errored" })).toBe("Stopped: the answer ended errored.");
  expect(failedLine({ code: "internal", message: "the run failed" })).toBe("The answer failed: the run failed.");
});
