// Pure: what the search over the whole app (Cmd-K) offers, and which keys
// the shell answers. What is typed can start a session; then the page's own
// commands, the shell's actions, the left bar's places, the settings, and
// the sessions the left bar holds, by title. No React, no fetch.
import type { PaletteCommand } from "../../design/kit/CommandPalette";
import { opensPalette } from "../../design/kit/overlayModel";
import type { NavEntry, SettingsEntry } from "../product";

export const SEARCH_PLACEHOLDER = "Search sessions, settings, and actions";

/** "Start a session: ‹text›", for what is typed: it opens Home with the text
 * in the composer, where the agent and the project are chosen. */
export function startCommands(query: string, start: (text: string) => void): PaletteCommand[] {
  const text = query.trim();
  if (!text) return [];
  return [{ id: "start", label: `Start a session: ${text}`, hint: "New session", run: () => start(text) }];
}

export function shellCommands(input: {
  page: readonly PaletteCommand[] | null;
  actions: readonly PaletteCommand[];
  nav: readonly NavEntry[];
  settings: readonly SettingsEntry[];
  sessions: readonly { id: string; title: string; kind: string }[];
  go: (to: string) => void;
}): PaletteCommand[] {
  const { go } = input;
  return [
    ...(input.page ?? []).map((command) => ({ ...command, id: `page-${command.id}`, hint: command.hint ?? "This page" })),
    ...input.actions.map((command) => ({ ...command, hint: command.hint ?? "Action" })),
    ...input.nav.map((entry) => ({ id: `nav-${entry.id}`, label: entry.label, hint: "Go to", run: () => go(entry.to) })),
    ...input.settings.flatMap((entry) => {
      const to = entry.routes[0]?.path;
      return to === undefined
        ? []
        : [{ id: `settings-${entry.id}`, label: entry.label, keywords: [entry.group, entry.about], hint: "Settings", run: () => go(to) }];
    }),
    ...input.sessions.map((session) => ({
      id: `session-${session.id}`,
      label: session.title,
      keywords: [session.kind],
      hint: "Session",
      run: () => go(`/sessions/${session.id}`),
    })),
  ];
}

export type ShellKey = "palette" | "sidebar" | "settings";

/** The shell's own shortcuts: Cmd-K searches, Cmd-B folds the left bar, and
 * Cmd-, opens Settings (Ctrl on a keyboard without Cmd). */
export function shellKey(event: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }): ShellKey | null {
  if (opensPalette(event)) return "palette";
  if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return null;
  if (event.key.toLowerCase() === "b") return "sidebar";
  if (event.key === ",") return "settings";
  return null;
}
