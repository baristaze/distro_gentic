// Each session's right pane, kept across visits in this browser: its width,
// its open tabs, the active one, whether a person hid it, and the tabs that
// have opened themselves. Like the preferences, it is the UI's alone, so
// local storage is its place; `paneModel.ts` decides every change.
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { NEW_PANE, parsePanes, rememberPane, type PaneState } from "../features/session/paneModel";

export const PANES_STORAGE_KEY = "acme.portal.panes";

interface PanesState {
  panes: Record<string, PaneState>;
  /** Applies `change` to one session's pane, a new one when it has none. */
  change: (sessionId: string, change: (pane: PaneState) => PaneState) => void;
}

export const usePanesStore = create<PanesState>()(
  persist(
    (set) => ({
      panes: {},
      change: (sessionId, change) =>
        set((state) => {
          const before = state.panes[sessionId] ?? NEW_PANE;
          const after = change(before);
          return after === before ? state : { panes: rememberPane(state.panes, sessionId, after) };
        }),
    }),
    {
      name: PANES_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ panes: state.panes }),
      // A pane the stored state names wrongly is a new one's; a field the
      // store does not know is dropped.
      merge: (stored, current) => ({ ...current, panes: parsePanes((stored as { panes?: unknown } | undefined)?.panes) }),
    },
  ),
);

/** One session's pane as kept, or a new one. */
export const paneOf = (panes: Readonly<Record<string, PaneState>>, sessionId: string): PaneState => panes[sessionId] ?? NEW_PANE;
