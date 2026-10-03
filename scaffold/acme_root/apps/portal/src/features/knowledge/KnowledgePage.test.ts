// @vitest-environment jsdom
// The knowledge list and one entry's page over a fake transport that
// answers as the API does: each org reads its own entries, and one another
// org holds answers 404. A suggestion is kept or rejected only by a member
// who may write, and an edit names the version it was read at.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KnowledgeView } from "@acme/client";
import { buttons, container, enter, mount, newNet, notFound, PEOPLE, press, unmount, writes, type Call } from "../screenTesting";
import { EntryPage } from "./EntryPage";
import { KnowledgePage } from "./KnowledgePage";

const net = vi.hoisted(() => ({}) as ReturnType<typeof newNet>);
vi.mock("../../app/api", async () => (await import("../screenTesting")).fakeApi(net));
vi.mock("../../app/AppNav", () => ({ AppNav: () => null }));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const entry = (org: "a" | "b", title: string, status: KnowledgeView["status"]): KnowledgeView => ({
  id: `k${org}`,
  title,
  trigger: ["release"],
  text: "Releases go out on **Tuesday**.",
  status,
  suggested_by: status === "suggested" ? "s1" : null,
  reviewed_by: status === "suggested" ? null : PEOPLE[org].id,
  version: 3,
  created_at: "2026-10-03T10:00:00Z",
  updated_at: "2026-10-03T10:00:00Z",
});
const HELD = { a: entry("a", "Ajax release day", "suggested"), b: entry("b", "Beta release day", "reviewed") };

function answer(call: Call): unknown {
  const held = HELD[net.org];
  if (call.method === "GET" && call.path.startsWith("/v1/knowledge?")) return call.path.includes(`status=${held.status}`) ? [held] : [];
  if (call.path === `/v1/knowledge/${held.id}`) return call.method === "PUT" ? { ...held, ...(call.body as object), version: 4 } : held;
  if (call.path === `/v1/knowledge/${held.id}/review`) return { ...held, status: (call.body as { keep: boolean }).keep ? "reviewed" : "rejected" };
  if (call.method === "POST" && call.path === "/v1/knowledge") return { ...held, id: "knew" };
  return notFound(call.path);
}

const routes = [
  { path: "/knowledge", Component: KnowledgePage },
  { path: "/knowledge/:entryId", Component: EntryPage },
];

beforeEach(() => Object.assign(net, newNet(), { answer }));
afterEach(unmount);

describe("the knowledge list", () => {
  it("lists the org's entries in the state chosen, none of another's", async () => {
    await mount(routes, "/knowledge?status=suggested");
    expect(container.querySelector("table[aria-label='Entries']")!.textContent).toContain("Ajax release day");
    expect(container.textContent).not.toContain("Beta release day");
    expect(net.calls.some((call) => call.path.startsWith("/v1/knowledge?status=suggested&"))).toBe(true);
  });

  it("writes an entry with its words", async () => {
    await mount(routes, "/knowledge");
    await enter("Title", "Release day");
    await enter("Recalled by", "release, deploy");
    await enter("What a session should know (Markdown)", "On Tuesday.");
    await press("Write the entry");
    expect(writes(net)).toEqual([{ method: "POST", path: "/v1/knowledge", body: { title: "Release day", trigger: ["release", "deploy"], text: "On Tuesday." } }]);
  });

  it("offers a viewer no form", async () => {
    net.role = "viewer";
    await mount(routes, "/knowledge");
    expect(container.querySelectorAll("form")).toHaveLength(0);
  });
});

describe("an entry's page", () => {
  it("shows nothing of an entry another org holds", async () => {
    await mount(routes, "/knowledge/kb");
    expect(container.querySelector("h1")!.textContent).toBe("No entry here");
    expect(container.textContent).not.toContain("Beta release day");
  });

  it("draws the text as Markdown and keeps a suggestion on a review", async () => {
    await mount(routes, "/knowledge/ka");
    expect(container.querySelector("[data-entry] strong")!.textContent).toBe("Tuesday");
    await press("Keep");
    expect(writes(net)).toEqual([{ method: "POST", path: "/v1/knowledge/ka/review", body: { keep: true } }]);
  });

  it("edits on the version read", async () => {
    await mount(routes, "/knowledge/ka");
    await press("Edit the entry");
    await enter("Title", "Release day, moved");
    await press("Save");
    expect(writes(net)).toEqual([
      { method: "PUT", path: "/v1/knowledge/ka", body: { title: "Release day, moved", trigger: ["release"], text: "Releases go out on **Tuesday**." }, ifMatch: 3 },
    ]);
  });

  it("offers a viewer no review and no edit", async () => {
    net.role = "viewer";
    await mount(routes, "/knowledge/ka");
    expect(buttons()).not.toContain("Keep");
    expect(buttons()).not.toContain("Edit the entry");
  });
});
