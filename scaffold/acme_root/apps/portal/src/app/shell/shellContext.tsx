// What the shell lends the screens inside it: a page offers its own commands
// to the search while it is mounted, and a control opens the search or the
// keyboard shortcuts.
import { createContext, useContext, useEffect } from "react";
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
