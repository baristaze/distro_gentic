import { expect, it } from "vitest";
import type { ParkView } from "@acme/client";
import { noticeLine, outageNotices } from "./outageModel";

const parked = (unlock: string, retry_at: string | null = null, reason: ParkView["reason"] = "provider") => ({ park: { reason, unlock, retry_at } });
const when = (iso: string) => iso.slice(11, 16);

it("says nothing when no session waits on a provider", () => {
  expect(outageNotices([{ park: null }, parked("approval", null, "person")])).toEqual([]);
});

it("groups the waiting sessions by provider and cause, with the earliest retry", () => {
  const notices = outageNotices([
    parked("anthropic", "2026-10-03T10:05:00Z"),
    parked("anthropic", "2026-10-03T10:02:00Z"),
    parked("openai:key"),
    parked("openai:billing"),
  ]);
  expect(notices).toEqual([
    { provider: "anthropic", cause: "out", detail: "", sessions: 2, retryAt: "2026-10-03T10:02:00Z" },
    { provider: "openai", cause: "key", detail: "key", sessions: 1, retryAt: null },
    { provider: "openai", cause: "refused", detail: "billing", sessions: 1, retryAt: null },
  ]);
  expect(notices.map((notice) => noticeLine(notice, when))).toEqual([
    "Anthropic is not answering. 2 sessions wait, and try again by themselves from 10:02.",
    "1 session waits for the org's own key to OpenAI: none is live.",
    "OpenAI refused the org's calls (billing). 1 session waits on it.",
  ]);
});

it("says a lone session tries again by itself", () => {
  const [notice] = outageNotices([parked("anthropic", "2026-10-03T10:05:00Z")]);
  expect(noticeLine(notice!, when)).toBe("Anthropic is not answering. 1 session waits, and tries again by itself from 10:05.");
});
