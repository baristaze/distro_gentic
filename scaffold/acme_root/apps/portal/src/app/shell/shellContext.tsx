// What the shell lends the screens inside it: a page offers its own commands
// to the search while it is mounted, a control opens the search or the
// keyboard shortcuts, and a page reads the sessions the shell keeps live.
import { createContext, useContext, useEffect } from "react";
import type { AgentSessionView } from "@acme/client";
import type { PaletteCommand } from "../../design/kit";

export interface ShellActions {
  /** The page's commands, listed first in the search; null when it goes. */
  offer: (commands: readonly PaletteCommand[] | null) => void;
  openSearch: () => void;
  openShortcuts: () => void;
}

export const ShellContext = createContext<ShellActions>({
  offer: () => undefined,
  openSearch: () => undefined,
  openShortcuts: () => undefined,
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
