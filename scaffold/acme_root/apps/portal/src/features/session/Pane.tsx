// A session's right pane: its open tabs, each with its icon, label, and ✕;
// a "+" that lists the views not open; the active tab's view under them;
// and the edge a person drags, or moves by the arrows, to resize it.
import { CloseTabIcon, Menu, MenuItem, PanelIcon, PlusIcon, Tooltip, useSplitter } from "../../design/kit";
import { PANE } from "./paneModel";
import type { SessionVm } from "./useSessionVm";

export function Pane({ vm }: { vm: SessionVm }) {
  const pane = vm.pane;
  const splitter = useSplitter(pane.width, vm.resizePane, PANE, "left");
  const active = vm.tabs.find((tab) => tab.id === pane.shown);
  if (!active || !vm.slotSession) return null;
  return (
    <aside className="acme-pane" aria-label="Session pane" style={{ width: pane.width }}>
      <div className="acme-pane-splitter" aria-label="Resize the panel" title="Drag to resize; double-click resets" {...splitter} />
      <div className="acme-pane-head">
        <div className="acme-pane-tabs" role="tablist" aria-label="The session's views">
          {pane.open.map((tab) => (
            <div key={tab.id} className="acme-pane-tab" data-active={tab.id === active.id || undefined}>
              <Tooltip tip={tab.tip}>
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
