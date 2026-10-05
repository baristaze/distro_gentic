// A short line about a control, shown while the pointer rests on it or the
// keyboard is on it: what it does and its shortcut. It floats over the page
// at the control's edge, so a scrolling pane never cuts it, and the control
// names it as its description. `InfoTip` is an ⓘ that says what a field
// means.
import { cloneElement, useEffect, useId, useRef, useState, type CSSProperties, type ReactElement, type ReactNode } from "react";
import { InfoIcon } from "./icons";
import { tipPlace, type TipSide } from "./tooltipModel";

/** How long the pointer rests before the tip shows; the keyboard shows it at once. */
const REST_MS = 350;

export function Tooltip({
  tip,
  shortcut,
  side = "bottom",
  children,
}: {
  tip: ReactNode;
  /** The keys that do the same, drawn after the words: "⌘K". */
  shortcut?: string;
  side?: TipSide;
  /** One element that takes a ref-free `aria-describedby`: a button or a link. */
  children: ReactElement<{ "aria-describedby"?: string }>;
}) {
  const id = useId();
  const anchor = useRef<HTMLSpanElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [place, setPlace] = useState<CSSProperties | null>(null);

  const show = () => {
    const rect = anchor.current?.getBoundingClientRect();
    if (rect) setPlace(tipPlace(rect, side));
  };
  const rest = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(show, REST_MS);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    setPlace(null);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    if (place === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPlace(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [place]);

  return (
    <span
      ref={anchor}
      className="acme-tip-anchor"
      onPointerEnter={rest}
      onPointerLeave={hide}
      onPointerDown={hide}
      onFocus={(event) => {
        if ((event.target as HTMLElement).matches?.(":focus-visible")) show();
      }}
      onBlur={hide}
    >
      {cloneElement(children, { "aria-describedby": id })}
      <span id={id} role="tooltip" className="acme-tooltip" hidden={place === null} style={place ?? undefined} data-side={side}>
        {tip}
        {shortcut ? <kbd className="acme-tooltip-keys">{shortcut}</kbd> : null}
      </span>
    </span>
  );
}

/** An ⓘ beside a field's name: a hover, a focus, or a tap shows what it means. */
export function InfoTip({ label, children, side = "top" }: { label: string; children: ReactNode; side?: TipSide }) {
  return (
    <Tooltip tip={children} side={side}>
      <button type="button" className="acme-info-tip" aria-label={label}>
        <InfoIcon size={14} />
      </button>
    </Tooltip>
  );
}
