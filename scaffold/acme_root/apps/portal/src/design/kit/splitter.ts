// The handle on a pane's edge: drag it to resize the pane, double-click it
// to go back to the pane's first width, or move it by the arrows once the
// keyboard is on it. The pane keeps its width where the caller keeps it.
import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { clampWidth, draggedWidth, keyedWidth, type PaneBounds } from "./splitterModel";

export interface SplitterProps {
  role: "separator";
  tabIndex: number;
  "aria-orientation": "vertical";
  "aria-valuenow": number;
  "aria-valuemin": number;
  "aria-valuemax": number;
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLElement>) => void;
  onDoubleClick: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

/** The props of the handle for a pane `width` wide; `onWidth` takes each new width. */
export function useSplitter(width: number, onWidth: (width: number) => void, bounds: PaneBounds, edge: "right" | "left" = "right"): SplitterProps {
  const drag = useRef<{ start: number; fromX: number } | null>(null);
  const now = clampWidth(width, bounds);
  return {
    role: "separator",
    tabIndex: 0,
    "aria-orientation": "vertical",
    "aria-valuenow": now,
    "aria-valuemin": bounds.min,
    "aria-valuemax": bounds.max,
    onPointerDown: (event) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      drag.current = { start: now, fromX: event.clientX };
    },
    onPointerMove: (event) => {
      if (drag.current === null) return;
      onWidth(draggedWidth(drag.current.start, drag.current.fromX, event.clientX, bounds, edge));
    },
    onPointerUp: (event) => {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      drag.current = null;
    },
    onDoubleClick: () => onWidth(bounds.initial),
    onKeyDown: (event) => {
      const next = keyedWidth(now, event.key, bounds, edge);
      if (next === null) return;
      event.preventDefault();
      onWidth(next);
    },
  };
}
