// Pure: what Settings' own bar lists. The sections in their groups, each
// group where its first section is (the platform's first, then a product's),
// narrowed by what is typed in "Search settings"; and the key that opens that
// search. No React, no fetch.
import type { SettingsEntry } from "../product";

export const SETTINGS_SEARCH_PLACEHOLDER = "e.g. API keys";

export interface SettingsGroup {
  name: string;
  entries: SettingsEntry[];
}

/** Whether every word typed is in the section's name, its group, or what it holds. */
function matches(entry: SettingsEntry, words: readonly string[]): boolean {
  const text = `${entry.label} ${entry.group} ${entry.about}`.toLowerCase();
  return words.every((word) => text.includes(word));
}

/** The sections by group, in the order they were given, narrowed by `query`;
 * a group with no section left is dropped. */
export function settingsGroups(entries: readonly SettingsEntry[], query = ""): SettingsGroup[] {
  const words = query.toLowerCase().split(/\s+/).filter((word) => word !== "");
  const groups: SettingsGroup[] = [];
  for (const entry of entries) {
    if (!matches(entry, words)) continue;
    const group = groups.find((each) => each.name === entry.group);
    if (group) group.entries.push(entry);
    else groups.push({ name: entry.group, entries: [entry] });
  }
  return groups;
}

/** A section's address: its first page's. */
export function sectionAddress(entry: SettingsEntry): string | null {
  return entry.routes[0]?.path ?? null;
}

/** Whether a key press opens "Search settings": a bare "/", typed outside a field. */
export function opensSettingsSearch(event: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean }, inField: boolean): boolean {
  return event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !inField;
}

/** Whether an address is inside Settings, where its own bar replaces the left bar. */
export function inSettings(pathname: string): boolean {
  return pathname === "/settings" || pathname.startsWith("/settings/");
}
