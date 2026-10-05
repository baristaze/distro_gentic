// A session's right pane: its open tabs, each with its icon, label, and ✕;
// a "+" that lists the views not open; the active tab's view under them;
// and the edge a person drags, or moves by the arrows, to resize it. When
// the support dock needs the room, the pane folds to its icon rail: a tab's
// icon shows its view over the story's edge, and a second click, or Esc,
// folds it again. A tab or a step asked for from outside the rail (a call
// line, a command, the address) shows there too.
import { useEffect, useState, type KeyboardEvent } from "react";
import { CloseTabIcon, Menu, MenuItem, PanelIcon, PlusIcon, Tooltip, useSplitter } from "../../design/kit";
import { PANE } from "./paneModel";
import type { SessionVm } from "./useSessionVm";

export function Pane({ vm, folded = false }: { vm: SessionVm; folded?: boolean }) {
  const pane = vm.pane;
  const splitter = useSplitter(pane.width, vm.resizePane, PANE, "left");
  const active = vm.tabs.find((tab) => tab.id === pane.shown);
  const [peek, setPeek] = useState(false);
  // An ask waits until the pane shows: folded, it opens the peek; in full,
  // the person sees it there.
  const [answered, setAnswered] = useState(0);
  if (active && vm.slotSession && pane.asks !== answered) {
    setAnswered(pane.asks);
    if (folded) setPeek(true);
  }
  // The active tab stays in sight when the strip holds more than fits.
  useEffect(() => {
    document.getElementById(`pane-tab-${pane.shown}`)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [pane.shown]);
  if (!active || !vm.slotSession) return null;
  if (folded) {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      setPeek(false);
    };
    return (
      <aside className="acme-pane" data-rail="" aria-label="Session pane" onKeyDown={onEscape}>
        <div className="acme-pane-rail" role="toolbar" aria-label="The session's views" aria-orientation="vertical">
          {pane.open.map((tab) => {
            const showing = peek && tab.id === active.id;
            return (
              <Tooltip key={tab.id} tip={`${tab.label} · ${tab.tip}`} side="left">
                <button
                  type="button"
                  className="acme-icon-button"
                  aria-label={tab.label}
                  aria-pressed={showing}
                  data-active={tab.id === active.id || undefined}
                  onClick={() => {
                    if (showing) {
                      setPeek(false);
                      return;
                    }
                    vm.openTab(tab.id);
                    setPeek(true);
                  }}
                >
                  {tab.icon}
                </button>
              </Tooltip>
            );
          })}
        </div>
        {peek ? (
          <div className="acme-pane-peek" role="region" aria-label={active.label} style={{ width: pane.width }}>
            <div className="acme-pane-head">
              <strong className="acme-pane-peek-name">
                {active.icon}
                {active.label}
              </strong>
              <Tooltip tip="Fold it to the rail" shortcut="Esc">
                <button type="button" className="acme-icon-button" aria-label={`Fold ${active.label}`} onClick={() => setPeek(false)}>
                  <CloseTabIcon />
                </button>
              </Tooltip>
            </div>
            <div className="acme-pane-view" id="pane-view" data-tab={active.id}>
              {active.render(vm.slotSession)}
            </div>
          </div>
        ) : null}
      </aside>
    );
  }
  return (
    <aside className="acme-pane" aria-label="Session pane" style={{ width: pane.width }}>
      <div className="acme-pane-splitter" aria-label="Resize the panel" title="Drag to resize; double-click resets" {...splitter} />
      <div className="acme-pane-head">
        <div className="acme-pane-tabs" role="tablist" aria-label="The session's views">
          {pane.open.map((tab) => (
            <div key={tab.id} className="acme-pane-tab" data-active={tab.id === active.id || undefined}>
              <Tooltip tip={`${tab.label} · ${tab.tip}`}>
                <button
                  type="button"
                  role="tab"
                  id={`pane-tab-${tab.id}`}
                  aria-selected={tab.id === active.id}
                  aria-controls="pane-view"
                  className="acme-pane-tab-name"
                  onClick={() => vm.openTab(tab.id)}
                >
                  {tab.icon}
                  <span>{tab.label}</span>
                </button>
              </Tooltip>
              <button type="button" className="acme-pane-tab-close" aria-label={`Close ${tab.label}`} title={`Close ${tab.label}`} onClick={() => vm.closeTab(tab.id)}>
                <CloseTabIcon size={14} />
              </button>
            </div>
          ))}
        </div>
        <Menu
          label="Open a view"
          trigger={<PlusIcon />}
          triggerLabel="Open a view"
          triggerTitle="Open a view"
          triggerClassName="acme-icon-button"
          align="end"
          disabled={pane.addable.length === 0}
        >
          {pane.addable.map((tab) => (
            <MenuItem key={tab.id} icon={tab.icon} onSelect={() => vm.openTab(tab.id)}>
              {tab.label}
            </MenuItem>
          ))}
        </Menu>
        <Tooltip tip="Hide the panel" shortcut="⌥⌘B">
          <button type="button" className="acme-icon-button" aria-label="Hide the panel" onClick={vm.togglePane}>
            <PanelIcon />
          </button>
        </Tooltip>
      </div>
      <div className="acme-pane-view" id="pane-view" role="tabpanel" aria-labelledby={`pane-tab-${active.id}`} data-tab={active.id}>
        {active.render(vm.slotSession)}
      </div>
    </aside>
  );
}
