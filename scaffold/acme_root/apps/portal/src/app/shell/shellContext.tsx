// What the shell lends the screens inside it: a page offers its own commands
// to the search while it is mounted, a control opens the search, the
// keyboard shortcuts, or support, a page reads the sessions the shell keeps
// live, and a page that splits itself folds its pane when the dock needs
// the room.
import { createContext, useContext, useEffect } from "react";
import type { AgentSessionView } from "@acme/client";
import type { PaletteCommand } from "../../design/kit";

export interface ShellActions {
  /** The page's commands, listed first in the search; null when it goes. */
  offer: (commands: readonly PaletteCommand[] | null) => void;
  openSearch: () => void;
  openShortcuts: () => void;
  /** Opens the support dock, or closes it while it is open. */
  toggleSupport: () => void;
}

export const ShellContext = createContext<ShellActions>({
  offer: () => undefined,
  openSearch: () => undefined,
  openShortcuts: () => undefined,
  toggleSupport: () => undefined,
});

export function useShellActions(): ShellActions {
  return useContext(ShellContext);
}

/** Offers `commands` in the shell's search while the calling page is mounted. */
export function usePageCommands(commands: readonly PaletteCommand[]): void {
  const { offer } = useShellActions();
  useEffect(() => {
    offer(commands);
    return () => offer(null);
  }, [commands, offer]);
}

/** The sessions the shell keeps live for its left bar: every parked one,
 * and the newest. A page reads a tree beneath it from them, with no read of
 * its own; outside the shell there are none. */
export const ShellSessionsContext = createContext<readonly AgentSessionView[]>([]);

export function useShellSessions(): readonly AgentSessionView[] {
  return useContext(ShellSessionsContext);
}

/** What the shell and a page that splits itself tell each other: the
 * page's pane width while it shows, and whether a pane of a width folds to
 * its rail to make room for the support dock. */
export interface PaneSplit {
  folds: (width: number | null) => boolean;
  setPane: (width: number | null) => void;
}

export const PaneSplitContext = createContext<PaneSplit>({ folds: () => false, setPane: () => undefined });

/** Tells the shell the page's pane width while it shows (null while it does
 * not), and answers whether the pane folds to its rail for the dock. The
 * answer is for the width the page has now, so the render that first shows
 * the pane already shows it folded. */
export function usePaneSplit(width: number | null): boolean {
  const { folds, setPane } = useContext(PaneSplitContext);
  useEffect(() => {
    setPane(width);
    return () => setPane(null);
  }, [width, setPane]);
  return folds(width);
}
