// The store runs here without a browser: an in-memory Storage twin stands in
// for the origin's local storage.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "acme.portal.preferences";

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

let local: MemoryStorage;

beforeEach(() => {
  local = new MemoryStorage();
  vi.stubGlobal("localStorage", local);
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("preferences store", () => {
  it("follows the system until a theme is picked, and keeps the pick", async () => {
    const { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().theme).toBe("system");
    usePreferencesStore.getState().setTheme("dark");
    expect(JSON.parse(local.getItem(KEY) as string).state).toMatchObject({ theme: "dark" });
  });

  it("reads a stored theme back, and an unknown one as the system's", async () => {
    local.setItem(KEY, JSON.stringify({ state: { theme: "light" }, version: 0 }));
    let { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState().theme).toBe("light");
    vi.resetModules();
    local.setItem(KEY, JSON.stringify({ state: { theme: "sepia" }, version: 0 }));
    ({ usePreferencesStore } = await import("./preferences"));
    expect(usePreferencesStore.getState().theme).toBe("system");
  });

  it("drops a stored field it does not know", async () => {
    local.setItem(KEY, JSON.stringify({ state: { theme: "dark", other: "x" }, version: 0 }));
    const { usePreferencesStore } = await import("./preferences");
    expect(usePreferencesStore.getState()).not.toHaveProperty("other");
    usePreferencesStore.getState().setTheme("light");
    expect(JSON.parse(local.getItem(KEY) as string).state).not.toHaveProperty("other");
  });

  it("keeps the left bar's width inside its bounds, its fold, and its filter", async () => {
    local.setItem(
      KEY,
      JSON.stringify({ state: { sidebarWidth: 9000, sidebarFolded: "yes", sessionFilter: { owner: "mine", status: "lost" } }, version: 0 }),
    );
    const { usePreferencesStore, SIDEBAR } = await import("./preferences");
    const state = usePreferencesStore.getState();
    expect(state.sidebarWidth).toBe(SIDEBAR.max);
    expect(state.sidebarFolded).toBe(false);
    expect(state.sessionFilter).toEqual({ owner: "mine", status: "any", kind: "", archived: false });
    state.setSidebarWidth(10);
    state.toggleSidebar();
    expect(JSON.parse(local.getItem(KEY) as string).state).toMatchObject({ sidebarWidth: SIDEBAR.min, sidebarFolded: true });
  });
});
