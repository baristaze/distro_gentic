import { expect, it } from "vitest";
import type { SettingsEntry } from "../product";
import { inSettings, opensSettingsSearch, sectionAddress, settingsGroups } from "./settingsNavModel";

const entry = (group: string, id: string, label: string, about = ""): SettingsEntry => ({
  group,
  id,
  label,
  icon: null,
  about,
  routes: [{ path: `/settings/${id}` }],
});
const ENTRIES = [
  entry("Personal", "profile", "Profile", "Your name and the theme"),
  entry("Organization", "members", "Members", "Who is in the org"),
  entry("Agents", "projects", "Projects", "Repositories and their credentials"),
  entry("Organization", "audit", "Audit", "What happened"),
  entry("Security", "api-keys", "API keys", "Keys a program calls with"),
  entry("Lab", "places", "Places", "Where work runs"),
];
const shape = (groups: ReturnType<typeof settingsGroups>) => groups.map((group) => [group.name, group.entries.map((each) => each.id)]);

it("groups the sections where each group first appears, keeping their order", () => {
  expect(shape(settingsGroups(ENTRIES))).toEqual([
    ["Personal", ["profile"]],
    ["Organization", ["members", "audit"]],
    ["Agents", ["projects"]],
    ["Security", ["api-keys"]],
    ["Lab", ["places"]],
  ]);
});

it("narrows by every word typed, in the name, the group, or what a section holds, and drops an empty group", () => {
  expect(shape(settingsGroups(ENTRIES, "api"))).toEqual([["Security", ["api-keys"]]]);
  expect(shape(settingsGroups(ENTRIES, "  ORGANIZATION  happened "))).toEqual([["Organization", ["audit"]]]);
  expect(shape(settingsGroups(ENTRIES, "repositories"))).toEqual([["Agents", ["projects"]]]);
  expect(settingsGroups(ENTRIES, "nothing like it")).toEqual([]);
});

it("names a section by its first page", () => {
  expect(sectionAddress(ENTRIES[0]!)).toBe("/settings/profile");
  expect(sectionAddress({ ...ENTRIES[0]!, routes: [] })).toBeNull();
});

it("opens the search on a bare slash typed outside a field", () => {
  const key = (k: string, mods: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean }> = {}) => ({ key: k, metaKey: false, ctrlKey: false, altKey: false, ...mods });
  expect(opensSettingsSearch(key("/"), false)).toBe(true);
  expect(opensSettingsSearch(key("/"), true)).toBe(false);
  expect(opensSettingsSearch(key("/", { metaKey: true }), false)).toBe(false);
  expect(opensSettingsSearch(key("k"), false)).toBe(false);
});

it("knows the addresses inside Settings", () => {
  expect(["/settings", "/settings/", "/settings/projects/p1"].map(inSettings)).toEqual([true, true, true]);
  expect(["/", "/sessions", "/settingsx"].map(inSettings)).toEqual([false, false, false]);
});
