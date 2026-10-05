// The left bar's sessions: grouped by what they ask of a person, sub-agents
// nested under their parent, a folded parent saying what it holds, and
// nothing that needs a person hidden in a quieter group; and the toast a
// session raises when it starts to need its person.
import type { AgentSessionView, ParkView } from "@acme/client";
import { expect, it } from "vitest";
import { ago, DEFAULT_FILTER, groupOf, needingYou, nextToasts, NO_TOASTS, parseFilter, RECENT_MAX, shellGroups, statusWords, treeWords, waitingBeneath, type ShellRow } from "./shellModel";

let clock = 0;
function session(id: string, over: Partial<AgentSessionView> = {}): AgentSessionView {
  clock += 1;
  return {
    id,
    title: `Session ${id}`,
    kind: "engineer",
    kind_version: 1,
    status: "idle",
    park: null,
    parent_id: null,
    root_id: over.parent_id ?? id,
    created_by: "u1",
    created_at: `2026-10-05T10:${String(clock).padStart(2, "0")}:00Z`,
    archived_at: null,
    deleted_at: null,
    ...over,
  };
}
const park = (reason: ParkView["reason"], unlock: string): ParkView => ({ reason, unlock, retry_at: null });
const ids = (rows: readonly ShellRow[]) => rows.map((row) => row.id);
const options = { filter: DEFAULT_FILTER, me: "u1" };

it("groups rows into Needs you, Running, and Recent", () => {
  const sessions = [
    session("asks", { status: "parked", park: park("person", "approval") }),
    session("runs", { status: "running" }),
    session("starts", { status: "pending" }),
    session("waits", { status: "parked", park: park("resource", "workspace") }),
    session("done"),
  ];
  const groups = shellGroups(sessions, options);
  expect(ids(groups.needsYou)).toEqual(["asks"]);
  expect(ids(groups.running)).toEqual(["waits", "starts", "runs"]);
  expect(ids(groups.recent)).toEqual(["done"]);
});

it("nests children under their parent, oldest first, and counts a session read twice once", () => {
  const parent = session("parent", { status: "running" });
  const first = session("first", { parent_id: "parent", root_id: "parent" });
  const second = session("second", { parent_id: "parent", root_id: "parent", status: "running" });
  const grandchild = session("grand", { parent_id: "second", root_id: "parent" });
  const groups = shellGroups([second, parent, grandchild, first, parent], options);
  expect(ids(groups.running)).toEqual(["parent"]);
  expect(ids(groups.running[0]!.children)).toEqual(["first", "second"]);
  expect(ids(groups.running[0]!.children[1]!.children)).toEqual(["grand"]);
  expect(groups.recent).toEqual([]);
});

it("lifts a tree into Needs you when a child needs a person, so the child is never hidden", () => {
  const parent = session("parent", { status: "parked", park: park("children", "children") });
  const child = session("child", { parent_id: "parent", status: "parked", park: park("person", "approval") });
  const groups = shellGroups([parent, child], { ...options, held: new Map([["child", "run_command"]]) });
  expect(ids(groups.needsYou)).toEqual(["parent"]);
  expect(groups.needsYou[0]!.children[0]).toMatchObject({ id: "child", dot: "needs", words: "Needs your decision: run_command" });
  expect(groups.running).toEqual([]);
});

it("shows a child whose parent is not read as a row of its own", () => {
  const groups = shellGroups([session("orphan", { parent_id: "gone", status: "running" })], options);
  expect(ids(groups.running)).toEqual(["orphan"]);
});

it("keeps the newest thirty in Recent", () => {
  const many = Array.from({ length: RECENT_MAX + 5 }, (_, n) => session(`s${n}`));
  const recent = shellGroups(many, options).recent;
  expect(recent).toHaveLength(RECENT_MAX);
  expect(recent[0]!.id).toBe(`s${RECENT_MAX + 4}`);
});

it("narrows by owner, agent, status, and leaves the archived out unless asked", () => {
  const sessions = [
    session("mine"),
    session("theirs", { created_by: "u2" }),
    session("analysis", { kind: "analysis" }),
    session("archived", { archived_at: "2026-10-05T11:00:00Z" }),
    session("running", { status: "running" }),
  ];
  const shown = (filter: Partial<typeof DEFAULT_FILTER>) => {
    const groups = shellGroups(sessions, { filter: { ...DEFAULT_FILTER, ...filter }, me: "u1" });
    return [...groups.needsYou, ...groups.running, ...groups.recent].map((row) => row.id).sort();
  };
  expect(shown({})).toEqual(["analysis", "mine", "running", "theirs"]);
  expect(shown({ owner: "mine" })).toEqual(["analysis", "mine", "running"]);
  expect(shown({ kind: "analysis" })).toEqual(["analysis"]);
  expect(shown({ status: "running" })).toEqual(["running"]);
  expect(shown({ archived: true })).toContain("archived");
  expect(groupOf(sessions[3]!)).toBe("recent");
});

it("says each status in words", () => {
  expect(statusWords(session("a", { status: "parked", park: park("person", "approval") }))).toBe("Needs your decision");
  expect(statusWords(session("b", { status: "parked", park: park("person", "principal") }))).toBe("Needs you: naming a principal for it");
  expect(statusWords(session("c", { status: "parked", park: park("resource", "workspace") }))).toBe("Waiting for a workspace");
  expect(statusWords(session("d", { status: "parked", park: park("pause", "resume") }))).toBe("Paused");
  expect(statusWords(session("e", { status: "pending" }))).toBe("Starting");
  expect(statusWords(session("f"))).toBe("Done");
  expect(statusWords(session("g", { archived_at: "2026-10-05T11:00:00Z" }))).toBe("Archived");
});

it("reads a stored filter field by field", () => {
  expect(parseFilter({ owner: "mine", status: "idle", kind: "analysis", archived: true })).toEqual({
    owner: "mine",
    status: "idle",
    kind: "analysis",
    archived: true,
  });
  expect(parseFilter({ owner: "all", status: "gone", kind: 3 })).toEqual(DEFAULT_FILTER);
  expect(parseFilter(null)).toEqual(DEFAULT_FILTER);
});

it("says how long ago, in the row's short words", () => {
  const now = new Date("2026-10-05T12:00:00Z");
  expect(ago("2026-10-05T11:59:30Z", now)).toBe("now");
  expect(ago("2026-10-05T11:55:00Z", now)).toBe("5m");
  expect(ago("2026-10-05T09:00:00Z", now)).toBe("3h");
  expect(ago("2026-10-03T12:00:00Z", now)).toBe("2d");
  expect(ago("not a time", now)).toBe("");
});

it("counts a parent's sub-agents at every depth and how many need a person, which its folded row says", () => {
  const groups = shellGroups(
    [
      session("root", { status: "parked", park: park("children", "children") }),
      session("reads", { parent_id: "root", root_id: "root", status: "running" }),
      session("asks", { parent_id: "root", root_id: "root", status: "parked", park: park("person", "answer") }),
      session("deep", { parent_id: "reads", root_id: "root", status: "parked", park: park("person", "approval") }),
    ],
    options,
  );
  const [root] = groups.needsYou;
  expect(root!.tree).toEqual({ count: 3, needsYou: 2 });
  expect(root!.children.find((row) => row.id === "reads")!.tree).toEqual({ count: 1, needsYou: 1 });
  expect(treeWords(root!.tree)).toBe("3 sub-agents · 2 need you");
  expect(treeWords({ count: 2, needsYou: 1 })).toBe("2 sub-agents · 1 needs you");
  expect(treeWords({ count: 1, needsYou: 0 })).toBe("1 sub-agent");
});

it("raises a toast when a session of the person's, or a sub-agent in a tree of theirs, starts to need them", () => {
  const quiet = [
    session("mine", { status: "running" }),
    session("child", { parent_id: "theirs-root", root_id: "mine", status: "running", created_by: "u9" }),
    session("theirs", { status: "running", created_by: "u2" }),
  ];
  // The first read takes what already waits as seen: the left bar shows it.
  const first = nextToasts(NO_TOASTS, needingYou([...quiet, session("waiting", { status: "parked", park: park("person", "answer") })], "u1"), null);
  expect(first.toasts).toEqual([]);
  const asking = quiet.map((one) => (one.id === "child" ? { ...one, status: "parked" as const, park: park("person", "answer") } : one));
  const holding = asking.map((one) => (one.id === "theirs" || one.id === "mine" ? { ...one, status: "parked" as const, park: park("person", "approval") } : one));
  const raised = nextToasts(first, needingYou(holding, "u1", new Map([["mine", "run_command"]])), null);
  expect(raised.toasts.map((toast) => [toast.id, toast.need, toast.asks])).toEqual([
    ["mine", "Approve run_command", false],
    ["child", "Answer its question", true],
  ]);
  // Nothing new: the same state, so the page draws nothing again.
  expect(nextToasts(raised, needingYou(holding, "u1", new Map([["mine", "run_command"]])), null)).toBe(raised);
  // Its page opening, or the need clearing, drops its toast; none comes back.
  const opened = nextToasts(raised, needingYou(holding, "u1", new Map([["mine", "run_command"]])), "child");
  expect(opened.toasts.map((toast) => toast.id)).toEqual(["mine"]);
  expect(nextToasts(opened, needingYou(quiet, "u1"), null).toasts).toEqual([]);
});

it("finds, for each child, a session beneath it at any depth that waits on a person", () => {
  const onChildren = { status: "parked" as const, park: park("children", "children") };
  const asks = { status: "parked" as const, park: park("person", "answer") };
  const sessions = [
    session("root", onChildren),
    session("lead", { ...onChildren, parent_id: "root" }),
    session("helper", { ...asks, parent_id: "lead", title: "Check the fixture" }),
    session("helper", { ...asks, parent_id: "lead", title: "Check the fixture" }),
    session("deep", { ...onChildren, parent_id: "root" }),
    session("middle", { ...onChildren, parent_id: "deep" }),
    session("bottom", { ...asks, parent_id: "middle", title: "  " }),
    session("quiet", { status: "running", parent_id: "root" }),
    session("gone", { ...asks, parent_id: "quiet", archived_at: "2026-10-05T11:00:00Z" }),
    session("self", { ...asks, parent_id: "root" }),
  ];
  const found = waitingBeneath(sessions, [{ id: "lead" }, { id: "deep" }, { id: "quiet" }, { id: "self" }]);
  expect([...found]).toEqual([
    ["lead", { id: "helper", title: "Check the fixture" }],
    ["deep", { id: "bottom", title: "Untitled" }],
  ]);
  // A loop in the links ends the walk.
  expect(waitingBeneath([session("a", { parent_id: "b" }), session("b", { parent_id: "a" })], [{ id: "a" }]).size).toBe(0);
});
