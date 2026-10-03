// One of a set of things, alone over the page and as large as the window
// lets it be: a picture, or a record too wide for its card. The arrows go
// to the next and the one before, Escape and a click on the backdrop close
// it, Tab stays inside, and closing puts the keyboard back where it was.
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { keepTabInside, useReturnFocus } from "./focus";
import { lightboxStep } from "./overlayModel";

export interface LightboxItem {
  title: string;
  content: ReactNode;
}

export function Lightbox({
  items,
  index,
  onIndex,
  onClose,
}: {
  items: readonly LightboxItem[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useReturnFocus();
  useEffect(() => close.current?.focus(), []);
  const item = items[index];
  if (!item) return null;
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    const next = lightboxStep(index, items.length, event.key);
    if (next !== null) {
      event.preventDefault();
      onIndex(next);
      return;
    }
    keepTabInside(event, box.current);
  };
  const many = items.length > 1;
  return (
    <div className="acme-dialog-backdrop acme-lightbox-backdrop" onClick={onClose}>
      <div
        ref={box}
        className="acme-lightbox"
        role="dialog"
        aria-modal="true"
        aria-label={item.title}
        onKeyDown={onKey}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="acme-lightbox-head">
          <h2 className="acme-card-title">{item.title}</h2>
          {many ? (
            <span className="acme-lightbox-count">
              {index + 1} of {items.length}
            </span>
          ) : null}
          {many ? (
            <>
              <button type="button" className="acme-button" data-tone="plain" onClick={() => onIndex(lightboxStep(index, items.length, "ArrowLeft")!)}>
                Previous
              </button>
              <button type="button" className="acme-button" data-tone="plain" onClick={() => onIndex(lightboxStep(index, items.length, "ArrowRight")!)}>
                Next
              </button>
            </>
          ) : null}
          <button ref={close} type="button" className="acme-button" data-tone="plain" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="acme-lightbox-body">{item.content}</div>
      </div>
    </div>
  );
}
