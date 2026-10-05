// Pure: the width a pane takes as its edge is dragged or moved by the
// keyboard, always inside its bounds.

export interface PaneBounds {
  min: number;
  max: number;
  /** The width a double-click goes back to. */
  initial: number;
}

/** How far one arrow press moves the edge, in pixels. */
export const KEY_STEP = 16;

export function clampWidth(width: number, bounds: PaneBounds): number {
  if (!Number.isFinite(width)) return bounds.initial;
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, width)));
}

/** The width while the edge is dragged: where it started, moved by how far
 * the pointer went. `edge` is the side of the pane the handle sits on, so a
 * pane on the right grows as the pointer moves left. */
export function draggedWidth(start: number, fromX: number, toX: number, bounds: PaneBounds, edge: "right" | "left" = "right"): number {
  const moved = toX - fromX;
  return clampWidth(start + (edge === "right" ? moved : -moved), bounds);
}

/** The width an arrow, Home, or End gives; null for any other key. */
export function keyedWidth(width: number, key: string, bounds: PaneBounds, edge: "right" | "left" = "right"): number | null {
  const grow = edge === "right" ? "ArrowRight" : "ArrowLeft";
  const shrink = edge === "right" ? "ArrowLeft" : "ArrowRight";
  if (key === grow) return clampWidth(width + KEY_STEP, bounds);
  if (key === shrink) return clampWidth(width - KEY_STEP, bounds);
  if (key === "Home") return bounds.min;
  if (key === "End") return bounds.max;
  return null;
}
