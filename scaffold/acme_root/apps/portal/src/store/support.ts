// The support conversation each person keeps in this browser: the id of
// their standing session with the platform assistant, one per org and
// person, so a visit continues it. Only the id is kept here; the session is
// read back from the API, and the dock continues it only when it is the
// person's own (`supportModel.ts`).
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export const SUPPORT_STORAGE_KEY = "acme.portal.support";

/** The most conversations kept: the newest win. */
export const CONVERSATIONS_KEPT = 20;

interface SupportState {
  /** Each person's conversation in an org, by `conversationKey`. */
  conversations: Record<string, string>;
  keep: (key: string, sessionId: string) => void;
  /** Starts the next message on a new conversation. */
  forget: (key: string) => void;
}

function parseConversations(stored: unknown): Record<string, string> {
  if (typeof stored !== "object" || stored === null) return {};
  const kept = Object.entries(stored).filter((entry): entry is [string, string] => typeof entry[1] === "string");
  return Object.fromEntries(kept.slice(-CONVERSATIONS_KEPT));
}

export const useSupportStore = create<SupportState>()(
  persist(
    (set) => ({
      conversations: {},
      keep: (key, sessionId) =>
        set((state) => {
          const others = Object.entries(state.conversations).filter(([one]) => one !== key);
          return { conversations: Object.fromEntries([...others, [key, sessionId]].slice(-CONVERSATIONS_KEPT)) };
        }),
      forget: (key) =>
        set((state) =>
          key in state.conversations ? { conversations: Object.fromEntries(Object.entries(state.conversations).filter(([one]) => one !== key)) } : state,
        ),
    }),
    {
      name: SUPPORT_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ conversations: state.conversations }),
      // A stored value that is not an id is dropped.
      merge: (stored, current) => ({ ...current, conversations: parseConversations((stored as { conversations?: unknown } | undefined)?.conversations) }),
    },
  ),
);
