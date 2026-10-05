// The signed-in app's frame: the left bar beside the page on show, the
// search over the whole app (Cmd-K), and the shell's keys (Cmd-B folds the
// bar, Cmd-, opens Settings). A page offers its own commands to the search
// through `usePageCommands`, and a control opens the search or the
// shortcuts through `useShellActions`.
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { CommandPalette, SidebarIcon, Tooltip, type PaletteCommand } from "../../design/kit";
import { usePreferencesStore } from "../../store/preferences";
import { useSlot } from "../slot";
import { THEME_CHOICES } from "../themeModel";
import { LeftBar } from "./LeftBar";
import { ShellContext, type ShellActions } from "./shellContext";
import { SEARCH_PLACEHOLDER, shellCommands, shellKey, startCommands } from "./paletteModel";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { useShellVm } from "./useShellVm";

export function Shell({ children }: { children: ReactNode }) {
  const vm = useShellVm();
  const slot = useSlot();
  const navigate = useNavigate();
  const setTheme = usePreferencesStore((s) => s.setTheme);
  const [searching, setSearching] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const [page, setPage] = useState<readonly PaletteCommand[] | null>(null);
  const offer = useCallback((commands: readonly PaletteCommand[] | null) => setPage(commands), []);
  const actions = useMemo<ShellActions>(
    () => ({ offer, openSearch: () => setSearching(true), openShortcuts: () => setShortcuts(true) }),
    [offer],
  );
  const { toggle } = vm;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const key = shellKey(event);
      if (key === null) return;
      event.preventDefault();
      if (key === "palette") setSearching(true);
      else if (key === "sidebar") toggle();
      else navigate("/settings");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, toggle]);

  const sessions = useMemo(
    () => [...vm.groups.needsYou, ...vm.groups.running, ...vm.groups.recent].flatMap(function every(row): { id: string; title: string; kind: string }[] {
      return [row, ...row.children.flatMap(every)];
    }),
    [vm.groups],
  );
  const commands = shellCommands({
    page,
    actions: [
      { id: "new", label: "New session", keywords: ["start", "home"], run: () => navigate("/") },
      { id: "all", label: "All sessions", keywords: ["list", "view all"], run: () => navigate("/sessions") },
      { id: "fold", label: vm.folded ? "Open the sidebar" : "Collapse the sidebar", run: toggle },
      { id: "settings", label: "Settings", run: () => navigate("/settings") },
      { id: "shortcuts", label: "Keyboard shortcuts", run: () => setShortcuts(true) },
      ...THEME_CHOICES.map((choice) => ({
        id: `theme-${choice.value}`,
        label: `Theme: ${choice.label}`,
        run: () => setTheme(choice.value),
      })),
    ],
    nav: slot.nav,
    settings: slot.settings,
    sessions,
    go: navigate,
  });

  return (
    <ShellContext.Provider value={actions}>
      <div className="acme-shell" data-folded={vm.folded || undefined} style={{ "--acme-sidebar-width": `${vm.width}px` } as CSSProperties}>
        {vm.folded ? null : <LeftBar vm={vm} nav={slot.nav} onSearch={actions.openSearch} />}
        <div className="acme-main">
          {vm.folded ? (
            <div className="acme-unfold">
              <Tooltip tip="Open sidebar" shortcut="⌘B" side="right">
                <button type="button" className="acme-icon-button" aria-label="Open sidebar" onClick={toggle}>
                  <SidebarIcon />
                </button>
              </Tooltip>
            </div>
          ) : null}
          {children}
        </div>
      </div>
      {searching ? (
        <CommandPalette
          commands={commands}
          placeholder={SEARCH_PLACEHOLDER}
          lead={(query) => startCommands(query, (text) => navigate("/", { state: { prompt: text } }))}
          onClose={() => setSearching(false)}
        />
      ) : null}
      {shortcuts ? <ShortcutsDialog onClose={() => setShortcuts(false)} /> : null}
    </ShellContext.Provider>
  );
}
