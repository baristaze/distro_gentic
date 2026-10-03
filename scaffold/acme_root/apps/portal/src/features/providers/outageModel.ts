// Pure: what the banner says when the org's sessions wait on a model
// provider. A park on a provider names it in its unlock: the provider alone
// while it is out (the park tries again by itself at its retry time), or the
// provider and a cause (`anthropic:key` while no key of the org's own is
// live). No React, no fetch.
import type { AgentSessionView, ProviderName } from "@acme/client";
import { countLine } from "../../app/recordModel";

export const PROVIDER_NAMES: Record<ProviderName, string> = { anthropic: "Anthropic", openai: "OpenAI" };

export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider as ProviderName] ?? provider;
}

export interface OutageNotice {
  provider: string;
  /** `out`: the provider does not answer; `key`: the org's key is missing or
   * refused; `refused`: the provider refused the calls for another cause. */
  cause: "out" | "key" | "refused";
  /** The cause as the park names it, for `refused`. */
  detail: string;
  sessions: number;
  /** The earliest a waiting session tries again by itself, when it does. */
  retryAt: string | null;
}

/** One notice per provider and cause, from the parked sessions the org
 * holds; nothing when none waits on a provider. */
export function outageNotices(sessions: readonly Pick<AgentSessionView, "park">[]): OutageNotice[] {
  const notices = new Map<string, OutageNotice>();
  for (const { park } of sessions) {
    if (park?.reason !== "provider") continue;
    const [provider = "", detail = ""] = park.unlock.split(":", 2);
    const cause: OutageNotice["cause"] = detail === "" ? "out" : detail === "key" ? "key" : "refused";
    const at = `${provider}:${cause}:${detail}`;
    const held = notices.get(at) ?? { provider, cause, detail, sessions: 0, retryAt: null };
    held.sessions += 1;
    if (park.retry_at && (held.retryAt === null || park.retry_at < held.retryAt)) held.retryAt = park.retry_at;
    notices.set(at, held);
  }
  return [...notices.values()].sort((a, b) => a.provider.localeCompare(b.provider) || a.cause.localeCompare(b.cause));
}

/** The notice in words. */
export function noticeLine(notice: OutageNotice, when: (iso: string) => string): string {
  const name = providerName(notice.provider);
  const waiting = `${countLine(notice.sessions, "session")} ${notice.sessions === 1 ? "waits" : "wait"}`;
  switch (notice.cause) {
    case "out":
      return notice.retryAt
        ? `${name} is not answering. ${waiting}, and ${notice.sessions === 1 ? "tries" : "try"} again by ${notice.sessions === 1 ? "itself" : "themselves"} from ${when(notice.retryAt)}.`
        : `${name} is not answering. ${waiting} on it.`;
    case "key":
      return `${waiting} for the org's own key to ${name}: none is live.`;
    case "refused":
      return `${name} refused the org's calls (${notice.detail.replace(/_/g, " ")}). ${waiting} on it.`;
  }
}
