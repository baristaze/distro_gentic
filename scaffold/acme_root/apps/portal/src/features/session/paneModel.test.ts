// The right pane as a person meets it: tabs open on demand and close, "+"
// offers what is not open (a product's tab among them), a tab opens itself
// once and never again, and each session keeps its own tabs and width
// across visits, the kept panes read back from local storage.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentSessionView } from "@acme/client";
import type { SessionTab, SlotSession } from "../../app/product";
import {
  addable,
  changedFiles,
  closeTab,
  delivered,
  KEPT_PANES,
  knownTabs,
  latestPlan,
  NEW_PANE,
  openCall,
  openTab,
  openThemselves,
  PANE,
  parsePane,
  rememberPane,
  resizePane,
  shownTab,
  stepOf,
  togglePane,
  type PaneState,
} from "./paneModel";
import { MAX_SHOWN, type Call } from "./timelineModel";

const at = "2026-10-05T10:00:00Z";
const call = (id: string, fields: Partial<Call>): Call => ({
  id,
  tool: "read_file",
  input: {},
  output: "{}",
  liveOutput: null,
  failure: null,
  state: "done",
  seq: 1,
  requestSeq: 1,
  startedAt: at,
  endedAt: at,
  ...fields,
});

describe("tabs", () => {
  it("open on demand, go to an open one, and close to their neighbour", () => {
    let pane = openTab(NEW_PANE, "workspace");
    pane = openTab(pane, "changes");
    pane = openTab(pane, "evidence");
    expect([pane.tabs, shownTab(pane)]).toEqual([["workspace", "changes", "evidence"], "evidence"]);
    pane = openTab(pane, "workspace");
    expect([pane.tabs, shownTab(pane)]).toEqual([["workspace", "changes", "evidence"], "workspace"]);
    pane = closeTab(pane, "workspace");
    expect([pane.tabs, shownTab(pane)]).toEqual([["changes", "evidence"], "changes"]);
    pane = closeTab(pane, "evidence");
    expect(shownTab(pane)).toBe("changes");
    pane = closeTab(pane, "changes");
    expect([pane.tabs, shownTab(pane)]).toEqual([[], null]);
  });

  it("hide and show with the pane, which opens its fallback when no tab is open", () => {
    const open = openTab(NEW_PANE, "evidence");
    const hidden = togglePane(open, "workspace");
    expect([hidden.tabs, shownTab(hidden)]).toEqual([["evidence"], null]);
    expect(shownTab(togglePane(hidden, "workspace"))).toBe("evidence");
    expect(shownTab(togglePane(NEW_PANE, "workspace"))).toBe("workspace");
    expect(shownTab(openTab(hidden, "plan"))).toBe("plan");
  });

  it("open a call in its tab, which keeps it as the step to show", () => {
    expect(openCall(NEW_PANE, "step", "u4")).toMatchObject({ tabs: ["step"], active: "step", step: "u4" });
  });

  it("keep the pane's width inside its bounds", () => {
    expect([resizePane(NEW_PANE, 10).width, resizePane(NEW_PANE, 5000).width, resizePane(NEW_PANE, 500).width]).toEqual([PANE.min, PANE.max, 500]);
  });

  it("drop a tab the portal no longer has, the active one moving", () => {
    const pane: PaneState = { ...NEW_PANE, tabs: ["workspace", "gone"], active: "gone" };
    expect(knownTabs(pane, new Set(["workspace"]))).toMatchObject({ tabs: ["workspace"], active: "workspace" });
  });
});

describe("a tab that opens itself", () => {
  it("opens once and becomes the active one; once closed, it stays closed", () => {
    let pane = openThemselves(NEW_PANE, ["workspace"]);
    expect([pane.tabs, shownTab(pane), pane.selfOpened]).toEqual([["workspace"], "workspace", ["workspace"]]);
    pane = closeTab(pane, "workspace");
    expect(openThemselves(pane, ["workspace"])).toBe(pane);
    // A later one opens once too: Changes once it delivers.
    pane = openThemselves(pane, ["workspace", "changes"]);
    expect([pane.tabs, shownTab(pane)]).toEqual([["changes"], "changes"]);
    expect(openThemselves(pane, ["changes"])).toBe(pane);
  });

  it("never shows a pane a person hid: it waits in it", () => {
    const hidden = togglePane(openTab(NEW_PANE, "evidence"), "workspace");
    const after = openThemselves(hidden, ["station"]);
    expect([after.tabs, shownTab(after), after.active]).toEqual([["evidence", "station"], null, "station"]);
  });
});

describe("+", () => {
  const record = { id: "s1", status: "running" } as AgentSessionView;
  const session: SlotSession = { session: record, calls: [], running: true, open: () => undefined };
  // A product's tab, offered only while the session runs.
  const station: SessionTab = { id: "station", label: "Station", icon: null, tip: "Its run", offered: (s) => s.running, render: () => null };

  it("offers each tab the session has something for that is not open, a slot's tab among them", () => {
    const offers = (s: SlotSession) => [
      { id: "workspace", offered: true, opensItself: false },
      { id: "plan", offered: false, opensItself: false },
      { id: station.id, offered: station.offered(s), opensItself: false },
    ];
    const pane = openTab(NEW_PANE, "workspace");
    expect(addable(pane, offers(session))).toEqual(["station"]);
    expect(addable(pane, offers({ ...session, running: false }))).toEqual([]);
    expect(addable(NEW_PANE, offers(session))).toEqual(["workspace", "station"]);
  });
});

describe("each session's pane, kept", () => {
  it("parses what local storage holds, a wrong value falling back to a new pane's", () => {
    expect(parsePane({ width: 9999, tabs: ["a", "a", 3, "b"], active: "c", hidden: "yes", selfOpened: "x" })).toEqual({
      width: PANE.max,
      tabs: ["a", "b"],
      active: "b",
      hidden: false,
      selfOpened: [],
      step: null,
    });
    expect(parsePane(null)).toEqual(NEW_PANE);
  });

  it("keeps the panes changed last, at most the kept number", () => {
    let panes: Record<string, PaneState> = {};
    for (let n = 0; n < KEPT_PANES + 5; n += 1) panes = rememberPane(panes, `s${n}`, NEW_PANE);
    panes = rememberPane(panes, "s7", openTab(NEW_PANE, "plan"));
    const kept = Object.keys(panes);
    expect(kept).toHaveLength(KEPT_PANES);
    expect(kept[kept.length - 1]).toBe("s7");
    expect(kept).not.toContain("s0");
  });
});

class MemoryStorage implements Storage {
  private items = new Map<string, string>();
  get length() {
    return this.items.size;
  }
  clear() {
    this.items.clear();
  }
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  key(index: number) {
    return [...this.items.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.items.delete(key);
  }
  setItem(key: string, value: string) {
    this.items.set(key, value);
  }
}

describe("the panes store", () => {
  let local: MemoryStorage;
  beforeEach(() => {
    local = new MemoryStorage();
    vi.stubGlobal("localStorage", local);
    vi.resetModules();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("keeps each session's tabs, active one, and width across visits, apart from every other session's", async () => {
    const first = await import("../../store/panes");
    first.usePanesStore.getState().change("s1", (pane) => resizePane(openTab(openTab(pane, "workspace"), "evidence"), 520));
    first.usePanesStore.getState().change("s2", (pane) => openTab(pane, "plan"));
    const stored = local.getItem(first.PANES_STORAGE_KEY);
    expect(stored).not.toBeNull();

    // A new visit reads them back.
    vi.resetModules();
    const again = await import("../../store/panes");
    await again.usePanesStore.persist.rehydrate();
    const panes = again.usePanesStore.getState().panes;
    expect(again.paneOf(panes, "s1")).toMatchObject({ tabs: ["workspace", "evidence"], active: "evidence", width: 520 });
    expect(again.paneOf(panes, "s2")).toMatchObject({ tabs: ["plan"], active: "plan", width: PANE.initial });
    expect(again.paneOf(panes, "s3")).toEqual(NEW_PANE);
  });

  it("remembers that a tab opened itself, so a new visit does not open it again", async () => {
    const first = await import("../../store/panes");
    first.usePanesStore.getState().change("s1", (pane) => closeTab(openThemselves(pane, ["workspace"]), "workspace"));
    vi.resetModules();
    const again = await import("../../store/panes");
    await again.usePanesStore.persist.rehydrate();
    const pane = again.paneOf(again.usePanesStore.getState().panes, "s1");
    expect(openThemselves(pane, ["workspace"]).tabs).toEqual([]);
  });
});

describe("what the platform's tabs read from the calls", () => {
  const calls = [
    call("u1", { tool: "write_plan", input: { plan: "1. Run it." } }),
    call("u2", { tool: "edit_file", input: { path: "src/dates.py", old_text: "a\n", new_text: "b\nc\n" } }),
    call("u3", { tool: "write_file", input: { path: "NOTES.md", text: "x\n" } }),
    call("u4", { tool: "edit_file", input: { path: "src/dates.py", old_text: "c\n", new_text: "d\n" } }),
    call("u5", { tool: "edit_file", input: { path: "src/held.py", old_text: "", new_text: "e\n" }, state: "held" }),
  ];

  it("lists each changed file with its lines, the last call that changed it opening it", () => {
    expect(changedFiles(calls)).toEqual([
      { path: "src/dates.py", added: 3, removed: 2, edits: 2, lastCall: "u4", cut: false },
      { path: "NOTES.md", added: 1, removed: 0, edits: 1, lastCall: "u3", cut: false },
    ]);
  });

  it("marks a file one of whose edits the view cut, whose lines it cannot count", () => {
    const long = call("u6", { tool: "write_file", input: { path: "NOTES.md", text: "x".repeat(MAX_SHOWN + 1) } });
    expect(changedFiles([...calls, long]).find((file) => file.path === "NOTES.md")?.cut).toBe(true);
    expect(changedFiles(calls).some((file) => file.cut)).toBe(false);
  });

  it("finds the last plan, the step a click names, and whether it delivered", () => {
    expect(latestPlan(calls)?.text).toBe("1. Run it.");
    expect(latestPlan([])).toBeNull();
    expect([stepOf(calls, "u2")?.id, stepOf(calls, "nope")?.id, stepOf(calls, null)?.id, stepOf([], null)]).toEqual(["u2", "u5", "u5", null]);
    expect(delivered(calls)).toBe(false);
    expect(delivered([...calls, call("u6", { tool: "open_pull_request" })])).toBe(true);
    expect(delivered([call("u7", { tool: "open_pull_request", state: "held" })])).toBe(false);
  });
});
