// The dock continues a conversation only when it is the person's own, of the
// platform assistant, and neither archived nor deleted; each person keeps
// their own in each org.
import { expect, it } from "vitest";
import { ASSISTANT_KIND, continues, conversationKey } from "./supportModel";

const mine = { kind: ASSISTANT_KIND, created_by: "u1", archived_at: null, deleted_at: null };

it("continues the person's own conversation with the assistant", () => {
  expect(continues(mine, "u1")).toBe(true);
});

it("never continues another member's, another kind's, an archived or a deleted session, or one before the person is known", () => {
  expect(continues({ ...mine, created_by: "u2" }, "u1")).toBe(false);
  expect(continues({ ...mine, kind: "engineer" }, "u1")).toBe(false);
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
