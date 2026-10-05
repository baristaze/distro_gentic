// Preferences only the UI knows about, kept across visits: the theme the
// person picked, or the system's; the left bar's width, whether it is
// folded away, what its sessions list shows, and which rows fold their
// sub-agents. Local storage is the right
// place for a preference; the session token is the one thing that never
// goes there.
import { parseTheme, type ThemePreference } from "../app/themeModel";
import { DEFAULT_FILTER, parseFilter, type SessionFilter } from "../app/shell/sessionFilter";
import { clampWidth, type PaneBounds } from "../design/kit/splitterModel";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export const PREFERENCES_STORAGE_KEY = "acme.portal.preferences";

/** The left bar: 260 pixels at first, between 200 and 420. */
export const SIDEBAR: PaneBounds = { min: 200, max: 420, initial: 260 };

/** The most rows whose fold is kept: the newest folds win. */
export const FOLDS_KEPT = 200;

interface PreferencesState {
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  sidebarWidth: number;
  setSidebarWidth: (width: number) => void;
  sidebarFolded: boolean;
  toggleSidebar: () => void;
  sessionFilter: SessionFilter;
  setSessionFilter: (filter: SessionFilter) => void;
  /** The sessions whose row folds its sub-agents away. */
  foldedTrees: string[];
  toggleTree: (id: string) => void;
}

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      theme: "system",
      setTheme: (theme) => set({ theme }),
      sidebarWidth: SIDEBAR.initial,
      setSidebarWidth: (width) => set({ sidebarWidth: clampWidth(width, SIDEBAR) }),
      sidebarFolded: false,
      toggleSidebar: () => set((state) => ({ sidebarFolded: !state.sidebarFolded })),
      sessionFilter: DEFAULT_FILTER,
      setSessionFilter: (sessionFilter) => set({ sessionFilter }),
      foldedTrees: [],
      toggleTree: (id) =>
        set((state) => ({
          foldedTrees: state.foldedTrees.includes(id) ? state.foldedTrees.filter((one) => one !== id) : [...state.foldedTrees, id].slice(-FOLDS_KEPT),
        })),
    }),
    {
      name: PREFERENCES_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        theme: state.theme,
        sidebarWidth: state.sidebarWidth,
        sidebarFolded: state.sidebarFolded,
        sessionFilter: state.sessionFilter,
        foldedTrees: state.foldedTrees,
      }),
      // A value the stored state does not name, or names wrongly, is the
      // default's; a field the store does not know is dropped.
      merge: (stored, current) => {
        const kept = (stored ?? {}) as Partial<Record<keyof PreferencesState, unknown>>;
        return {
          ...current,
          theme: parseTheme(kept.theme),
          sidebarWidth: clampWidth(typeof kept.sidebarWidth === "number" ? kept.sidebarWidth : SIDEBAR.initial, SIDEBAR),
          sidebarFolded: kept.sidebarFolded === true,
          sessionFilter: parseFilter(kept.sessionFilter),
          foldedTrees: Array.isArray(kept.foldedTrees) ? kept.foldedTrees.filter((id): id is string => typeof id === "string").slice(-FOLDS_KEPT) : [],
        };
      },
    },
  ),
);
