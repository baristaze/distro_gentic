// The signed-in app's frame: the left bar beside the page on show (inside
// Settings, Settings' own bar in its place), the support dock at the right
// edge while it is open, the search over the whole app (Cmd-K), and the
// shell's keys (Cmd-B folds the bar, Cmd-, opens Settings, Cmd-/ opens or
// closes support). A page offers its own commands to the search through
// `usePageCommands`, and a control opens the search, the shortcuts, or
// support through `useShellActions`. A session that starts to need its
// person raises a toast on any page. The dock keeps its conversation and
// its draft while the main area moves between pages; the shell starts over
// in another org, and so does the dock.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { CommandPalette, SidebarIcon, Tooltip, type PaletteCommand } from "../../design/kit";
import { usePreferencesStore } from "../../store/preferences";
import { shellRoutes } from "../product";
import { useSlot } from "../slot";
import { THEME_CHOICES } from "../themeModel";
import { CLOSED_DOCK, closeDock, dockLayout, navigated, openDock, setDraft, toggleDock, toggleExpanded, type DockState } from "./dockModel";
import { LeftBar } from "./LeftBar";
import { NeedsYouToasts } from "./NeedsYouToasts";
import { PaneSplitContext, ShellContext, ShellSessionsContext, type PaneSplit, type ShellActions } from "./shellContext";
import { SEARCH_PLACEHOLDER, shellCommands, shellKey, startCommands } from "./paletteModel";
import { SettingsBar } from "./SettingsBar";
import { inSettings } from "./settingsNavModel";
import { ShortcutsDialog } from "./ShortcutsDialog";
import { chipLinks, SupportDock } from "./SupportDock";
import { pageContext } from "./supportLinks";
import { useShellVm } from "./useShellVm";
import { useSupportVm } from "./useSupportVm";

/** The window's width, read again as it resizes. */
function useViewportWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const read = () => setWidth(window.innerWidth);
    window.addEventListener("resize", read);
    return () => window.removeEventListener("resize", read);
  }, []);
  return width;
}

export function Shell({ children }: { children: ReactNode }) {
  const vm = useShellVm();
  const slot = useSlot();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const setTheme = usePreferencesStore((s) => s.setTheme);
  const dockWidth = usePreferencesStore((s) => s.dockWidth);
  const setDockWidth = usePreferencesStore((s) => s.setDockWidth);
  const [searching, setSearching] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const [page, setPage] = useState<readonly PaletteCommand[] | null>(null);
  const [dock, setDock] = useState<DockState>(CLOSED_DOCK);
  const [pane, setPane] = useState<number | null>(null);
  const viewport = useViewportWidth();
  const offer = useCallback((commands: readonly PaletteCommand[] | null) => setPage(commands), []);
  const toggleSupport = useCallback(() => setDock(toggleDock), []);
  const actions = useMemo<ShellActions>(
    () => ({ offer, openSearch: () => setSearching(true), openShortcuts: () => setShortcuts(true), toggleSupport }),
    [offer, toggleSupport],
  );
  const { toggle } = vm;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const key = shellKey(event);
      if (key === null) return;
      event.preventDefault();
      if (key === "palette") setSearching(true);
      else if (key === "sidebar") toggle();
      else if (key === "support") toggleSupport();
      else navigate("/settings");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, toggle, toggleSupport]);

  // The dock beside the page, or over it, and whether the page's pane folds.
  const sidebar = vm.folded ? 0 : vm.width;
  const layout = dockLayout({ dock, viewport, sidebar, width: dockWidth, pane });
  // A page asks for the width its pane has now, so its answer does not wait
  // for the width to reach the shell.
  const { open, expanded } = dock;
  const split = useMemo<PaneSplit>(
    () => ({ folds: (width) => dockLayout({ dock: { open, expanded }, viewport, sidebar, width: dockWidth, pane: width }).paneFolded, setPane }),
    [open, expanded, viewport, sidebar, dockWidth],
  );
  // A move of the main area keeps the dock's conversation and draft; a sheet
  // closes and an expanded dock returns to the split, so the page shows.
  const mode = useRef(layout.mode);
  useEffect(() => {
    mode.current = layout.mode;
  }, [layout.mode]);
  const shown = useRef(pathname);
  useEffect(() => {
    if (shown.current === pathname) return;
    shown.current = pathname;
    setDock((before) => navigated(before, mode.current));
  }, [pathname]);
  const routes = useMemo(() => shellRoutes(slot), [slot]);
  const here = useMemo(() => pageContext(pathname, search, routes), [pathname, search, routes]);
  const support = useSupportVm(here);
  const links = useMemo(
    () =>
      chipLinks(routes, (to) => {
        setDock((before) => navigated(before, mode.current));
        navigate(to);
      }),
    [routes, navigate],
  );

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
      { id: "support", label: "Ask support", keywords: ["help", "assistant", "question"], run: () => setDock(openDock) },
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
      <div
        className="acme-shell"
        data-folded={vm.folded || undefined}
        data-dock={layout.mode === "closed" ? undefined : layout.mode}
        style={{ "--acme-sidebar-width": `${vm.width}px`, "--acme-dock-width": `${layout.width}px` } as CSSProperties}
      >
        {vm.folded ? null : inSettings(pathname) ? (
          <SettingsBar sections={slot.settings} onFold={toggle} />
        ) : (
          <LeftBar vm={vm} nav={slot.nav} onSearch={actions.openSearch} support={{ open: dock.open, toggle: toggleSupport }} />
        )}
        <div className="acme-main" hidden={layout.mode === "expanded"}>
          {vm.folded ? (
            <div className="acme-unfold">
              <Tooltip tip="Open sidebar" shortcut="⌘B" side="right">
                <button type="button" className="acme-icon-button" aria-label="Open sidebar" onClick={toggle}>
                  <SidebarIcon />
                </button>
              </Tooltip>
            </div>
          ) : null}
          <ShellSessionsContext.Provider value={vm.sessions}>
            <PaneSplitContext.Provider value={split}>{children}</PaneSplitContext.Provider>
          </ShellSessionsContext.Provider>
        </div>
        {layout.mode === "closed" ? null : (
          <SupportDock
            vm={support}
            mode={layout.mode}
            width={layout.width}
            draft={dock.draft}
            onDraft={(draft) => setDock((before) => setDraft(before, draft))}
            links={links}
            onClose={() => setDock(closeDock)}
            onExpand={() => setDock(toggleExpanded)}
            onResize={setDockWidth}
          />
        )}
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
      <NeedsYouToasts needing={vm.needing} ready={vm.read} />
    </ShellContext.Provider>
  );
}
