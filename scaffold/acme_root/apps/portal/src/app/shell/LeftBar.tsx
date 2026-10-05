// The left bar: what exists and what needs the person. The org chip, the
// search, New session, the platform's and the product's entries, the
// sessions grouped by what they ask (Needs you, Running, Recent) with each
// sub-agent under its parent, a tree whose parent row folds it, and the user
// chip. Its edge drags to resize.
import { useId, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import {
  ChevronRightIcon,
  FilterIcon,
  NewSessionIcon,
  Popover,
  SearchIcon,
  SegmentedControl,
  Select,
  SidebarIcon,
  Tooltip,
  useSplitter,
} from "../../design/kit";
import { AccountMenu } from "../AccountMenu";
import { OrgChip } from "../OrgChip";
import type { NavEntry } from "../product";
import { ago, treeWords, type ShellRow, type SessionFilter } from "./shellModel";
import type { ShellVm } from "./useShellVm";

const STATUS_OPTIONS: { value: SessionFilter["status"]; label: string }[] = [
  { value: "any", label: "Any status" },
  { value: "running", label: "Running" },
  { value: "parked", label: "Parked" },
  { value: "pending", label: "Pending" },
  { value: "idle", label: "Idle" },
];

const OWNER_OPTIONS: readonly { value: SessionFilter["owner"]; label: string }[] = [
  { value: "everyone", label: "Everyone" },
  { value: "mine", label: "Mine" },
];

function NavCount({ count }: { count: () => number | null }) {
  const n = count();
  return n ? <span className="acme-side-count">{n}</span> : null;
}

function SideLink({ to, icon, label, tip, end, count }: { to: string; icon: ReactNode; label: string; tip: string; end?: boolean; count?: () => number | null }) {
  return (
    <Tooltip tip={tip} side="right">
      <NavLink to={to} end={end} className="acme-side-link">
        {icon}
        <span className="acme-side-label">{label}</span>
        {count ? <NavCount count={count} /> : null}
      </NavLink>
    </Tooltip>
  );
}

/** Which rows fold their sub-agents, and the switch. */
interface Folds {
  folded: ReadonlySet<string>;
  toggle: (id: string) => void;
}

function Row({ row, now, folds }: { row: ShellRow; now: Date; folds: Folds }) {
  const parent = row.children.length > 0;
  const folded = parent && folds.folded.has(row.id);
  return (
    <li data-tree={parent ? (folded ? "folded" : "open") : undefined}>
      <div className="acme-side-row-line">
        <NavLink to={`/sessions/${row.id}`} className="acme-side-row" data-dot={row.dot}>
          <span className="acme-row-dot" data-dot={row.dot} aria-hidden="true" />
          <span className="acme-row-main">
            <span className="acme-row-title">{row.title}</span>
            <span className="acme-row-words">{row.words}</span>
            {folded ? (
              <span className="acme-row-tree" data-needs-you={row.tree.needsYou > 0 || undefined}>
                {treeWords(row.tree)}
              </span>
            ) : null}
          </span>
          <time className="acme-row-ago" dateTime={row.at}>
            {ago(row.at, now)}
          </time>
        </NavLink>
        {parent ? (
          <button
            type="button"
            className="acme-row-fold"
            aria-expanded={!folded}
            aria-label={folded ? `Show the sub-agents of ${row.title}` : `Fold the sub-agents of ${row.title}`}
            title={folded ? "Show its sub-agents" : "Fold its sub-agents"}
            onClick={() => folds.toggle(row.id)}
          >
            <ChevronRightIcon size={14} className="acme-fold-mark" />
          </button>
        ) : null}
      </div>
      {parent && !folded ? (
        <ul className="acme-row-children" aria-label={`Sub-agents of ${row.title}`}>
          {row.children.map((child) => (
            <Row key={child.id} row={child} now={now} folds={folds} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function Group({ label, rows, now, folds }: { label: string; rows: readonly ShellRow[]; now: Date; folds: Folds }) {
  const id = useId();
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby={id} className="acme-side-group">
      <h2 id={id} className="acme-side-group-title">
        {label}
        <span className="acme-side-group-count">{rows.length}</span>
      </h2>
      <ul aria-label={label} className="acme-side-rows">
        {rows.map((row) => (
          <Row key={row.id} row={row} now={now} folds={folds} />
        ))}
      </ul>
    </section>
  );
}

function FilterPanel({ vm }: { vm: ShellVm }) {
  const set = (change: Partial<SessionFilter>) => vm.setFilter({ ...vm.filter, ...change });
  return (
    <div className="acme-filter-panel">
      <SegmentedControl label="Whose sessions" value={vm.filter.owner} options={OWNER_OPTIONS} onChange={(owner) => set({ owner })} />
      <Select label="Status" value={vm.filter.status} options={STATUS_OPTIONS} onChange={(status) => set({ status: status as SessionFilter["status"] })} />
      <Select label="Agent" value={vm.filter.kind} options={[{ value: "", label: "Any agent" }, ...vm.kinds]} onChange={(kind) => set({ kind })} />
      <label className="acme-check">
        <input type="checkbox" checked={vm.filter.archived} onChange={(event) => set({ archived: event.target.checked })} />
        Show archived
      </label>
      {vm.filtered ? (
        <button type="button" className="acme-link" onClick={vm.clearFilter}>
          Show every session
        </button>
      ) : null}
    </div>
  );
}

export function LeftBar({ vm, nav, onSearch }: { vm: ShellVm; nav: readonly NavEntry[]; onSearch: () => void }) {
  const splitter = useSplitter(vm.width, vm.setWidth, vm.bounds);
  return (
    <aside className="acme-sidebar" aria-label="Sidebar">
      <div className="acme-sidebar-head">
        <OrgChip />
        <Tooltip tip="Collapse sidebar" shortcut="⌘B">
          <button type="button" className="acme-icon-button" aria-label="Collapse sidebar" onClick={vm.toggle}>
            <SidebarIcon />
          </button>
        </Tooltip>
      </div>
      <div className="acme-sidebar-top">
        <Tooltip tip="Search sessions, settings, and actions" shortcut="⌘K" side="right">
          <button type="button" className="acme-side-search" onClick={onSearch}>
            <SearchIcon />
            <span className="acme-side-label">Search</span>
            <kbd className="acme-keys">⌘K</kbd>
          </button>
        </Tooltip>
        <nav aria-label="Main" className="acme-side-nav">
          <SideLink to="/" end icon={<NewSessionIcon />} label="New session" tip="Describe a task and start an agent on it" />
          {nav.map((entry) => (
            <SideLink key={entry.id} to={entry.to} icon={entry.icon} label={entry.label} tip={entry.tip} count={entry.count} />
          ))}
        </nav>
      </div>
      <div className="acme-side-sessions-head">
        <span className="acme-side-heading">Sessions</span>
        <Popover
          label="Filter the sessions"
          triggerLabel={vm.filtered ? "Filter the sessions (on)" : "Filter the sessions"}
          triggerTitle="Filter the sessions"
          triggerClassName="acme-icon-button acme-filter-trigger"
          width={240}
          trigger={
            <>
              <FilterIcon />
              {vm.filtered ? <span className="acme-filter-on" aria-hidden="true" /> : null}
            </>
          }
        >
          <FilterPanel vm={vm} />
        </Popover>
        <Link to="/sessions" className="acme-side-viewall">
          View all
        </Link>
      </div>
      <div className="acme-sidebar-scroll">
        {vm.error ? <p className="acme-side-note">{vm.error}</p> : null}
        {vm.loading ? (
          <p className="acme-side-note">Loading</p>
        ) : vm.empty && !vm.error ? (
          <div className="acme-side-empty">
            {vm.filtered ? (
              <>
                <p>No session matches the filter.</p>
                <button type="button" className="acme-link" onClick={vm.clearFilter}>
                  Show every session
                </button>
              </>
            ) : (
              <p>No sessions yet. Describe a task on Home.</p>
            )}
          </div>
        ) : (
          <>
            <Group label="Needs you" rows={vm.groups.needsYou} now={vm.now} folds={vm.folds} />
            <Group label="Running" rows={vm.groups.running} now={vm.now} folds={vm.folds} />
            <Group label="Recent" rows={vm.groups.recent} now={vm.now} folds={vm.folds} />
          </>
        )}
      </div>
      <div className="acme-sidebar-foot">
        <AccountMenu />
      </div>
      <div className="acme-splitter" aria-label="Resize the sidebar" title="Drag to resize; double-click resets" {...splitter} />
    </aside>
  );
}
