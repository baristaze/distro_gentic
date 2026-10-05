// Pure: the support dock, the shell's own column at the right edge. The
// left bar is the shell's, the main area is the route's, and the dock is
// the shell's again: never two owners on one column. A page that splits
// itself (a session's story and its pane) splits inside the main area, and
// when the dock needs room, that pane yields first and folds to its icon
// rail; only then does the dock narrow, and the page's story never goes
// below its minimum. Under 1100 pixels the dock is a sheet over the main
// area. No React, no storage.
import { clampWidth, type PaneBounds } from "../../design/kit/splitterModel";

/** The dock: 400 pixels at first, between 320 and 640. */
export const DOCK: PaneBounds = { min: 320, max: 640, initial: 400 };

/** Under this many pixels of window, the dock is a sheet over the main area. */
export const SHEET_BELOW = 1100;

/** The narrowest a page's story goes, beside its own pane and the dock. */
export const STORY_MIN = 360;

/** A page's pane folded to its icon rail. */
export const RAIL = 48;

/** What the shell keeps of the dock while a person moves between pages. */
export interface DockState {
  open: boolean;
  /** The chat takes the main area's width. */
  expanded: boolean;
  /** What is typed and not yet sent. */
  draft: string;
}

export const CLOSED_DOCK: DockState = { open: false, expanded: false, draft: "" };

/** Where the dock sits: nowhere; a column beside the main area; a sheet
 * over it; or in its place. */
export type DockMode = "closed" | "side" | "sheet" | "expanded";

export interface DockLayout {
  mode: DockMode;
  /** The dock's width in pixels: 0 while closed, the main area's while expanded. */
  width: number;
  /** Whether the page's own pane folds to its rail to make room. */
  paneFolded: boolean;
}

export interface DockSpace {
  dock: Pick<DockState, "open" | "expanded">;
  /** The window's width. */
  viewport: number;
  /** The left bar's width; 0 while it is folded away. */
  sidebar: number;
  /** The width a person left the dock at. */
  width: number;
  /** The page's own pane while it shows, its width; null for a page with none. */
  pane: number | null;
}

/** Where the dock goes, and whether the page's pane folds for it. */
export function dockLayout(space: DockSpace): DockLayout {
  const { dock, viewport, pane } = space;
  if (!dock.open) return { mode: "closed", width: 0, paneFolded: false };
  const main = Math.max(0, viewport - space.sidebar);
  const wanted = clampWidth(space.width, DOCK);
  const sheet: DockLayout = { mode: "sheet", width: Math.min(wanted, main), paneFolded: false };
  if (viewport < SHEET_BELOW) return sheet;
  if (dock.expanded) return { mode: "expanded", width: main, paneFolded: false };
  // Everything fits as it is.
  if (main - wanted - (pane ?? 0) >= STORY_MIN) return { mode: "side", width: wanted, paneFolded: false };
  // The page's pane yields first, to its rail.
  const rail = pane === null ? 0 : RAIL;
  const folded = pane !== null;
  if (main - wanted - rail >= STORY_MIN) return { mode: "side", width: wanted, paneFolded: folded };
  // Then the dock narrows, down to its minimum.
  const room = main - rail - STORY_MIN;
  if (room >= DOCK.min) return { mode: "side", width: room, paneFolded: folded };
  // The story would go below its minimum: the dock covers the page instead.
  return sheet;
}

export function openDock(dock: DockState): DockState {
  return dock.open ? dock : { ...dock, open: true };
}

/** Closes the dock; it opens again at the split, its draft kept. */
export function closeDock(dock: DockState): DockState {
  return dock.open || dock.expanded ? { ...dock, open: false, expanded: false } : dock;
}

export function toggleDock(dock: DockState): DockState {
  return dock.open ? closeDock(dock) : openDock(dock);
}

export function toggleExpanded(dock: DockState): DockState {
  return { ...dock, expanded: !dock.expanded };
}

export function setDraft(dock: DockState, draft: string): DockState {
  return dock.draft === draft ? dock : { ...dock, draft };
}

/** The main area moved to another page, by a chip, the left bar, or the
 * page itself. The dock keeps its conversation and its draft. Expanded, it
 * returns to the split, so the page shows beside it; a sheet closes, so the
 * page it covered shows. */
export function navigated(dock: DockState, mode: DockMode): DockState {
  if (mode === "sheet") return closeDock(dock);
  if (dock.expanded) return { ...dock, expanded: false };
  return dock;
}
