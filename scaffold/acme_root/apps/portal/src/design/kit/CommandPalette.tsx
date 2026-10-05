// The things a page can do, found by typing: Cmd-K or Ctrl-K opens it, the
// letters narrow it, the arrows choose, Enter does the chosen one and closes
// it, and Escape closes it. A page passes only what it can do now; `lead`
// adds what the typed words themselves offer, first.
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { keepTabInside, useReturnFocus } from "./focus";
import { opensPalette, paletteStep, rankCommands } from "./overlayModel";

export interface PaletteCommand {
  id: string;
  label: string;
  /** Other words a person may type for it. */
  keywords?: readonly string[];
  /** What kind of thing it is, drawn muted at the end: "Session", "Settings". */
  hint?: string;
  run: () => void;
}

/** Listens for Cmd-K or Ctrl-K on the whole window while the page is open. */
export function usePaletteKey(onOpen: () => void): void {
  useEffect(() => {
    const listen = (event: globalThis.KeyboardEvent) => {
      if (!opensPalette(event)) return;
      event.preventDefault();
      onOpen();
    };
    window.addEventListener("keydown", listen);
    return () => window.removeEventListener("keydown", listen);
  }, [onOpen]);
}

export function CommandPalette({
  commands,
  onClose,
  placeholder = "Find a command",
  lead,
}: {
  commands: readonly PaletteCommand[];
  onClose: () => void;
  placeholder?: string;
  /** Commands made from what is typed, shown before the matches. */
  lead?: (query: string) => readonly PaletteCommand[];
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const listId = useId();
  useReturnFocus();
  useEffect(() => field.current?.focus(), []);
  const shown = [...(lead?.(query) ?? []), ...rankCommands(commands, query)];
  const chosen = shown[Math.min(active, shown.length - 1)];
  const run = (command: PaletteCommand | undefined) => {
    if (!command) return;
    onClose();
    command.run();
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      run(chosen);
      return;
    }
    const next = paletteStep(Math.min(active, shown.length - 1), shown.length, event.key);
    if (next !== null) {
      event.preventDefault();
      setActive(next);
      return;
    }
    keepTabInside(event, box.current);
  };
  const optionId = (command: PaletteCommand) => `${listId}-${command.id}`;
  return (
    <div className="acme-dialog-backdrop acme-palette-backdrop" onClick={onClose}>
      <div
        ref={box}
        className="acme-dialog acme-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Commands"
        onKeyDown={onKey}
        onClick={(event) => event.stopPropagation()}
      >
        <input
          ref={field}
          className="acme-field"
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={chosen ? optionId(chosen) : undefined}
          aria-label={placeholder}
          placeholder={placeholder}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
        />
        <ul id={listId} role="listbox" aria-label="Commands" className="acme-palette-list">
          {shown.length === 0 ? <li className="acme-palette-empty">No command matches</li> : null}
          {shown.map((command) => (
            <li
              key={command.id}
              id={optionId(command)}
              role="option"
              aria-selected={command === chosen}
              className="acme-palette-option"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => run(command)}
            >
              <span className="acme-palette-label">{command.label}</span>
              {command.hint ? <span className="acme-palette-hint">{command.hint}</span> : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
