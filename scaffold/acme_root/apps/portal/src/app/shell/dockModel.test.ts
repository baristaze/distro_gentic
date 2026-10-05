// The support dock never shares a column with the page: opening it on a
// session's page folds the page's pane to its rail before the story narrows,
// then narrows the dock to its minimum, and covers the page as a sheet when
// even that leaves the story short, or under 1100 pixels. A move to another
// page keeps its draft.
import { describe, expect, it } from "vitest";
import {
  CLOSED_DOCK,
  closeDock,
  DOCK,
  dockLayout,
  navigated,
  openDock,
  RAIL,
  setDraft,
  SHEET_BELOW,
  STORY_MIN,
  toggleDock,
  toggleExpanded,
  type DockSpace,
} from "./dockModel";

const open = openDock(CLOSED_DOCK);
const space = (over: Partial<DockSpace> = {}): DockSpace => ({ dock: open, viewport: 1440, sidebar: 260, width: DOCK.initial, pane: 440, ...over });
/** What the session's story keeps beside the dock and its own pane. */
const story = (s: DockSpace) => {
  const layout = dockLayout(s);
  return s.viewport - s.sidebar - layout.width - (s.pane === null ? 0 : layout.paneFolded ? RAIL : s.pane);
};

describe("opening the dock on a session's page", () => {
  it("leaves the page as it is while closed", () => {
    expect(dockLayout(space({ dock: CLOSED_DOCK }))).toEqual({ mode: "closed", width: 0, paneFolded: false });
  });

  it("sits beside the page and folds nothing when everything fits", () => {
    const wide = space({ viewport: 1920 });
    expect(dockLayout(wide)).toEqual({ mode: "side", width: DOCK.initial, paneFolded: false });
    expect(story(wide)).toBeGreaterThanOrEqual(STORY_MIN);
  });

  it("folds the page's pane to its rail before the story narrows, and keeps the dock's width", () => {
    // 1440 - 260 - 400 - 440 leaves the story 340: short of its 360.
    const short = space();
    expect(dockLayout(short)).toEqual({ mode: "side", width: DOCK.initial, paneFolded: true });
    expect(story(short)).toBe(1440 - 260 - DOCK.initial - RAIL);
  });

  it("narrows the dock only once the pane is folded, and never below its minimum or the story below its own", () => {
    // 1100 - 300 - 400 - 48 leaves 352: the dock gives 8 pixels.
    const tight = space({ viewport: 1100, sidebar: 300 });
    expect(dockLayout(tight)).toEqual({ mode: "side", width: 1100 - 300 - RAIL - STORY_MIN, paneFolded: true });
    expect(story(tight)).toBe(STORY_MIN);
  });

  it("narrows the dock on a page with no pane, with nothing to fold", () => {
    const plain = space({ viewport: 1100, sidebar: 380, pane: null });
    expect(dockLayout(plain)).toEqual({ mode: "side", width: 1100 - 380 - STORY_MIN, paneFolded: false });
  });

  it("covers the page as a sheet when its minimum would still leave the story short", () => {
    const crowded = space({ viewport: 1100, sidebar: 420 });
    expect(dockLayout(crowded)).toEqual({ mode: "sheet", width: DOCK.initial, paneFolded: false });
  });

  it("is a sheet over the main area under 1100 pixels, however the page splits", () => {
    expect(dockLayout(space({ viewport: SHEET_BELOW - 1 })).mode).toBe("sheet");
    expect(dockLayout(space({ viewport: 900, pane: null })).mode).toBe("sheet");
    // A sheet is never wider than the main area it covers.
    expect(dockLayout(space({ viewport: 500, sidebar: 0, width: 640 })).width).toBe(500);
    expect(dockLayout(space({ viewport: SHEET_BELOW })).mode).toBe("side");
  });

  it("takes the main area's width expanded, and folds nothing it no longer sits beside", () => {
    expect(dockLayout(space({ dock: toggleExpanded(open) }))).toEqual({ mode: "expanded", width: 1440 - 260, paneFolded: false });
    // Under 1100 pixels it is still a sheet.
    expect(dockLayout(space({ dock: toggleExpanded(open), viewport: 900 })).mode).toBe("sheet");
  });

  it("reads a stored width inside its bounds", () => {
    expect(dockLayout(space({ viewport: 2400, width: 9000 })).width).toBe(DOCK.max);
    expect(dockLayout(space({ viewport: 2400, width: Number.NaN })).width).toBe(DOCK.initial);
  });
});

describe("the dock across navigation", () => {
  const typed = setDraft(open, "why is it parked?");

  it("keeps its draft when the main area moves beside it", () => {
    expect(navigated(typed, "side")).toBe(typed);
  });

  it("returns to the split when expanded, so the page it opened shows, its draft kept", () => {
    const after = navigated(toggleExpanded(typed), "expanded");
    expect(after).toEqual({ open: true, expanded: false, draft: "why is it parked?" });
  });

  it("closes as a sheet, so the page it covered shows, and opens again with its draft", () => {
    const after = navigated(typed, "sheet");
    expect(after.open).toBe(false);
    expect(openDock(after).draft).toBe("why is it parked?");
  });

  it("opens, closes, and toggles, keeping what is typed", () => {
    expect(toggleDock(typed).open).toBe(false);
    expect(toggleDock(toggleDock(typed))).toEqual(typed);
    expect(closeDock(toggleExpanded(typed))).toEqual({ open: false, expanded: false, draft: "why is it parked?" });
    expect(closeDock(CLOSED_DOCK)).toBe(CLOSED_DOCK);
    expect(openDock(open)).toBe(open);
  });
});
