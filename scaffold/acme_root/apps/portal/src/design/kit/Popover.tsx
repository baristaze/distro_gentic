// A panel that opens from a button and holds controls, not a list of
// choices (that is a Menu): a filter, a small form. A click on the button
// opens it and the keyboard lands on its first control; Escape closes it and
// puts the keyboard back on the button; a click anywhere else, or the
// keyboard leaving it, closes it.
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { focusables } from "./focus";

export function Popover({
  label,
  trigger,
  triggerLabel,
  triggerTitle,
  triggerClassName = "acme-menu-trigger",
  align = "start",
  placement = "below",
  width = 280,
  children,
}: {
  /** What a screen reader calls the open panel. */
  label: string;
  /** What the button shows. */
  trigger: ReactNode;
  /** What a screen reader calls the button, when its content does not say it. */
  triggerLabel?: string;
  triggerTitle?: string;
  triggerClassName?: string;
  /** Which edge of the button the panel lines up with. */
  align?: "start" | "end";
  /** Whether the panel opens under the button or over it. */
  placement?: "below" | "above";
  width?: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  const close = () => {
    setOpen(false);
    button.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    focusables(panel.current)[0]?.focus();
    const outside = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  return (
    <div ref={root} style={{ position: "relative", minWidth: 0, display: "flex" }}>
      <button
        ref={button}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={triggerLabel}
        title={triggerTitle}
        onClick={() => setOpen((value) => !value)}
        className={triggerClassName}
      >
        {trigger}
      </button>
      {open ? (
        <div
          ref={panel}
          id={id}
          role="dialog"
          aria-label={label}
          className="acme-popover"
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            close();
          }}
          onBlur={(event) => {
            if (!root.current?.contains(event.relatedTarget as Node | null) && event.relatedTarget !== null) setOpen(false);
          }}
          style={{
            position: "absolute",
            [placement === "below" ? "top" : "bottom"]: "calc(100% + 6px)",
            [align === "end" ? "right" : "left"]: 0,
            zIndex: 30,
            width,
          }}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}
