// The keys the portal answers, in a dialog the user chip opens.
import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { keepTabInside, useReturnFocus } from "../../design/kit/focus";

export const SHORTCUTS: readonly { keys: string; does: string }[] = [
  { keys: "⌘K", does: "Search sessions, settings, and actions" },
  { keys: "⌘B", does: "Collapse or open the sidebar" },
  { keys: "⌘,", does: "Open Settings" },
  { keys: "⌘↵", does: "Send what you wrote" },
  { keys: "Esc", does: "Close a menu, a search, or a dialog" },
];

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useReturnFocus();
  useEffect(() => close.current?.focus(), []);
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    keepTabInside(event, box.current);
  };
  return (
    <div className="acme-dialog-backdrop" onClick={onClose}>
      <div
        ref={box}
        className="acme-dialog acme-confirm"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKey}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId} className="acme-card-title">
          Keyboard shortcuts
        </h2>
        <dl className="acme-shortcuts">
          {SHORTCUTS.map((shortcut) => (
            <div key={shortcut.keys}>
              <dt>
                <kbd className="acme-keys">{shortcut.keys}</kbd>
              </dt>
              <dd>{shortcut.does}</dd>
            </div>
          ))}
        </dl>
        <div className="acme-confirm-actions">
          <button ref={close} type="button" className="acme-button" data-tone="plain" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
