// Settings' own bar, in the left bar's place while an address is inside
// Settings: the way back to the app, "Search settings" (the "/" key), and the
// sections in their groups, the platform's and a product's alike.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { BackIcon, SearchIcon, SettingsIcon, SidebarIcon, Tooltip } from "../../design/kit";
import type { SettingsEntry } from "../product";
import { opensSettingsSearch, sectionAddress, SETTINGS_SEARCH_PLACEHOLDER, settingsGroups } from "./settingsNavModel";

function inField(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
}

export function SettingsBar({ sections, onFold }: { sections: readonly SettingsEntry[]; onFold: () => void }) {
  const navigate = useNavigate();
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const groups = settingsGroups(sections, query);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (!opensSettingsSearch(event, inField(event.target))) return;
      event.preventDefault();
      search.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Enter opens the first section the search leaves; Escape clears it.
  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setQuery("");
      return;
    }
    if (event.key !== "Enter") return;
    const first = groups[0]?.entries[0];
    const to = first ? sectionAddress(first) : null;
    if (to) navigate(to);
  };

  return (
    <aside className="acme-sidebar" aria-label="Settings sidebar">
      <div className="acme-sidebar-head">
        <Link to="/" className="acme-side-link acme-settings-back">
          <BackIcon />
          <span className="acme-side-label">Back to app</span>
        </Link>
        <Tooltip tip="Collapse sidebar" shortcut="⌘B">
          <button type="button" className="acme-icon-button" aria-label="Collapse sidebar" onClick={onFold}>
            <SidebarIcon />
          </button>
        </Tooltip>
      </div>
      <div className="acme-sidebar-top">
        <label className="acme-side-search acme-settings-search">
          <SearchIcon />
          <span className="acme-sr-only">Search settings</span>
          <input
            ref={search}
            type="search"
            value={query}
            placeholder={SETTINGS_SEARCH_PLACEHOLDER}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onSearchKey}
          />
          <kbd className="acme-keys">/</kbd>
        </label>
      </div>
      <nav aria-label="Settings" className="acme-sidebar-scroll acme-settings-nav">
        <NavLink to="/settings" end className="acme-side-link">
          <SettingsIcon />
          <span className="acme-side-label">Overview</span>
        </NavLink>
        {groups.length === 0 ? <p className="acme-side-note">No section matches.</p> : null}
        {groups.map((group) => (
          <section key={group.name} className="acme-side-group" aria-label={group.name}>
            <h2 className="acme-side-group-title">{group.name}</h2>
            <ul className="acme-side-rows">
              {group.entries.map((entry) => {
                const to = sectionAddress(entry);
                return to === null ? null : (
                  <li key={entry.id}>
                    <Tooltip tip={entry.about} side="right">
                      <NavLink to={to} className="acme-side-link">
                        {entry.icon}
                        <span className="acme-side-label">{entry.label}</span>
                      </NavLink>
                    </Tooltip>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </nav>
    </aside>
  );
}
