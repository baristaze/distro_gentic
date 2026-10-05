// A session's sub-agents across the panes, on the stack the timeline check
// runs (`portal_stack.py`). The scene never has a sub-agent ask its
// person, so `portal_check.py tree` first starts the scene's engineer and
// writes a tree through storage: one answer that starts two sub-agents, a
// park on them, the first one's report, and the second still at work. Its
// next beats park the second on its person, then end it. The owner reads
// the card that follows each child, opens a report's child and comes back
// from its first card, folds the parent's row in the left bar, and gets a
// toast on the page open when a sub-agent starts to need them. Then the
// engineer's scene runs for real: its answer starts two analysis
// sub-agents and parks on them, each runs and reports, and the engineer
// wakes. The owner watches the card follow each child live, reads each
// report, and finds its tree in the Sub-agents tab. Each view is shot light
// and dark under e2e/screenshots/.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { ORG, OWNER, signedIn, SLUG } from "./signIn";

const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
// The folder the runner clones the org's repository from (`portal_stack.py runner`).
const REPOSITORIES = process.env.PORTAL_REPOSITORIES;
const PROMPT = "Fix the failing test in tests/test_dates.py and open a pull request";
// What `portal_check.py tree` writes; the scene's sub-agents carry the same titles.
const ASKED = "Read every date in the app day first";
const READS = "Read how the other parsers take a date";
const CALLERS = "Check every caller of parse";

test.use({ viewport: { width: 1440, height: 900 } });

async function shoot(page: Page, name: string): Promise<void> {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.screenshot({ path: `${SHOTS}subagents-${name}-${scheme}.png`, animations: "disabled" });
  }
  await page.emulateMedia({ colorScheme: "light" });
}

type Box = { x: number; y: number; width: number; height: number };

/** Whether two boxes on the page share no point. */
function apart(a: Box, b: Box): boolean {
  return a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
}

/** The tree, or its next beat once its root is named; the last line printed. */
function tree(...root: string[]): string {
  const printed = execFileSync("uv", ["run", "--package", "acme-api", "python", "services/api/tests/portal_check.py", "tree", SLUG, ...root], {
    cwd: ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
  });
  return printed.trim().split("\n").pop()!;
}

test("a session's sub-agents: a card that follows each, a report that leads to its child and back, a row that folds, and a toast when one needs its person", async ({ browser }) => {
  const made = JSON.parse(tree()) as { root: string; children: [string, string] };
  const owner = await signedIn(browser, OWNER, ORG);
  await owner.goto(`/sessions/${made.root}`);
  await expect(owner.getByRole("heading", { level: 1, name: ASKED })).toBeVisible();
  const chat = owner.getByRole("list", { name: "Timeline" });

  // One card for the two its answer started, a row each that says where it stands.
  const card = chat.getByRole("region", { name: "Started 2 sub-agents" });
  const row = (title: string) => card.getByRole("listitem").filter({ hasText: title });
  await expect(row(READS)).toHaveAttribute("data-phase", "done");
  await expect(row(CALLERS)).toHaveAttribute("data-phase", "working");
  await expect(row(CALLERS)).toContainText("Searching for “parse(”");
  const waits = chat.locator("[data-kind='line']").filter({ hasText: "Waiting on 2 sub-agents" });
  await expect(waits).toContainText(`${READS}: done · ${CALLERS}: working`);
  console.log(`card: ${(await card.innerText()).split("\n").join(" | ")}`);
  console.log(`park: ${await waits.innerText()}`);
  await shoot(owner, "card-running");

  // The outline marks the person's message.
  const outline = owner.getByRole("navigation", { name: "Outline" });
  await outline.getByRole("button", { name: "Outline" }).click();
  await expect(outline.getByRole("list")).toContainText(ASKED);
  await shoot(owner, "outline");
  await outline.getByRole("button", { name: "Outline" }).click();

  // The report leads to its child, whose first card leads back.
  const report = chat.getByRole("region", { name: `Report from ${READS}` });
  await expect(report).toContainText("Ended succeeded");
  await report.getByRole("button", { name: "The report" }).click();
  await expect(report).toContainText("takes the month first");
  await report.scrollIntoViewIfNeeded();
  await shoot(owner, "report");
  await report.getByRole("link", { name: `Open ${READS}` }).click();
  await expect(owner.getByRole("heading", { level: 1, name: READS })).toBeVisible();
  expect(new URL(owner.url()).pathname).toBe(`/sessions/${made.children[0]}`);
  const from = chat.getByRole("region", { name: `From ${ASKED}` });
  await expect(from).toContainText("Read each parser under src/");
  await shoot(owner, "from");
  await from.getByRole("link", { name: ASKED }).click();
  await expect(owner.getByRole("heading", { level: 1, name: ASKED })).toBeVisible();

  // In the left bar, the parent's row folds its sub-agents and counts them.
  const bar = owner.getByRole("complementary", { name: "Sidebar" });
  const nested = bar.getByRole("list", { name: `Sub-agents of ${ASKED}` });
  await expect(nested).toContainText(READS);
  await expect(nested).toContainText(CALLERS);
  await bar.getByRole("button", { name: `Fold the sub-agents of ${ASKED}` }).click();
  await expect(nested).toHaveCount(0);
  await expect(bar.getByRole("link", { name: new RegExp(ASKED) })).toContainText("2 sub-agents");
  await shoot(owner, "tree-folded");

  // The child at work asks its person: a toast says so on the page open, its
  // row and the park follow it, and so do the status line and the folded row.
  expect(tree(made.root)).toBe(made.children[1]);
  const toasts = owner.getByRole("region", { name: "Sessions that need you" });
  await expect(toasts).toContainText(CALLERS, { timeout: 30_000 });
  await expect(toasts).toContainText("reads files from a US bank");
  await expect(row(CALLERS)).toHaveAttribute("data-phase", "needs_you");
  await expect(waits).toContainText(`${CALLERS}: needs you`);
  await expect(chat.getByRole("status")).toContainText(`Needs you in a sub-agent: ${CALLERS}`);
  await expect(bar.getByRole("link", { name: new RegExp(ASKED) })).toContainText("2 sub-agents · 1 needs you");
  // The toast leaves the composer and its Send clear: the person steers on.
  const composer = owner.getByRole("form", { name: "Send a message" });
  const send = composer.getByRole("button", { name: "Send" });
  await expect(send).toBeVisible();
  const [toast, under, button] = await Promise.all([toasts.boundingBox(), composer.boundingBox(), send.boundingBox()]);
  expect(apart(toast!, under!), "the toast clears the composer").toBe(true);
  expect(apart(toast!, button!), "the toast clears Send").toBe(true);
  console.log(`toast box: ${JSON.stringify(toast)} · send box: ${JSON.stringify(button)}`);
  console.log(`toast: ${(await toasts.innerText()).split("\n").join(" | ")}`);
  console.log(`status: ${await chat.getByRole("status").innerText()}`);
  await shoot(owner, "needs-you");

  // The toast opens the child that needs its person.
  await toasts.getByRole("button", { name: "Open", exact: true }).click();
  await expect(owner.getByRole("heading", { level: 1, name: CALLERS })).toBeVisible();
  await expect(toasts).toHaveCount(0);

  // The Sub-agents tab groups them by where each stands.
  await owner.goto(`/sessions/${made.root}?pane=subagents`);
  const tab = owner.getByRole("complementary", { name: "Session pane" }).getByRole("tabpanel");
  await expect(tab.getByRole("region", { name: "Needs you" })).toContainText(CALLERS);
  await expect(tab.getByRole("region", { name: "Done" })).toContainText(READS);
  await shoot(owner, "tab-subagents");

  // It takes its answer and ends: the card settles.
  expect(tree(made.root)).toBe(made.children[1]);
  await owner.goto(`/sessions/${made.root}`);
  await expect(row(CALLERS)).toHaveAttribute("data-phase", "done", { timeout: 30_000 });
  await expect(waits).toContainText(`${READS}: done · ${CALLERS}: done`);
  await shoot(owner, "card-settled");
});

test("the engineer's scene starts two sub-agents: a card that follows each live, a report from each, and its tree in the Sub-agents tab", async ({ browser }) => {
  test.skip(!REPOSITORIES, "PORTAL_REPOSITORIES names the folder the scene's runner clones from");
  execFileSync("uv", ["run", "--package", "acme-api", "python", "services/api/tests/portal_check.py", "scene", REPOSITORIES!, SLUG], {
    cwd: ROOT,
    stdio: "inherit",
  });
  const owner = await signedIn(browser, OWNER, ORG);
  await owner.getByRole("button", { name: /^Agent:/ }).click();
  await owner.getByRole("menuitemradio", { name: /^Engineer/ }).click();
  await owner.keyboard.press("Escape");
  await owner.getByRole("button", { name: /^Project:/ }).click();
  await owner.getByRole("menuitemradio", { name: "First project" }).click();
  await owner.keyboard.press("Escape");
  await owner.getByRole("textbox", { name: "Prompt" }).fill(PROMPT);
  await owner.getByRole("button", { name: "Send", exact: true }).click();
  await expect(owner.getByRole("heading", { level: 1, name: PROMPT })).toBeVisible();
  const sessionId = new URL(owner.url()).pathname.split("/").pop()!;
  const chat = owner.getByRole("list", { name: "Timeline" });

  // Its answer starts both: one card, a row each that follows its child as
  // it runs. The runner takes one loop at a time, so the second is still at
  // work while the first reads.
  const card = chat.getByRole("region", { name: "Started 2 sub-agents" });
  await expect(card).toBeVisible({ timeout: 90_000 });
  const row = (title: string) => card.getByRole("listitem").filter({ hasText: title });
  await expect(row(CALLERS)).toHaveAttribute("data-phase", "working");
  console.log(`card at work: ${(await card.innerText()).split("\n").join(" | ")}`);
  await card.scrollIntoViewIfNeeded();
  await shoot(owner, "scene-card-running");
  // Each ends and reports, and its row settles with no reload.
  await expect(row(READS)).toHaveAttribute("data-phase", "done", { timeout: 60_000 });
  await expect(row(CALLERS)).toHaveAttribute("data-phase", "done", { timeout: 60_000 });
  console.log(`card settled: ${(await card.innerText()).split("\n").join(" | ")}`);

  // A report card from each, read as data; woken by the second, the
  // engineer goes on.
  for (const [title, says] of [
    [READS, "takes the month first"],
    [CALLERS, "written day first"],
  ] as const) {
    const report = chat.getByRole("region", { name: `Report from ${title}` });
    await expect(report).toContainText("Ended succeeded");
    await report.getByRole("button", { name: "The report" }).click();
    await expect(report).toContainText(says);
    console.log(`report: ${(await report.innerText()).split("\n").join(" | ")}`);
  }
  await expect(chat).toContainText("Both reported", { timeout: 60_000 });
  await card.scrollIntoViewIfNeeded();
  await shoot(owner, "scene-card-settled");

  // The Sub-agents tab: both done, and the tree the engineer's kind roots.
  await owner.goto(`/sessions/${sessionId}?pane=subagents`);
  const tab = owner.getByRole("complementary", { name: "Session pane" }).getByRole("tabpanel");
  await expect(tab.getByRole("region", { name: "Done" })).toContainText(READS);
  await expect(tab.getByRole("region", { name: "Done" })).toContainText(CALLERS);
  await expect(tab).toContainText("Its tree has spawned 2 of the 10 sub-agents it may, at most 3 deep.");
  console.log(`tab: ${(await tab.innerText()).split("\n").join(" | ")}`);
  await shoot(owner, "scene-tab-subagents");
});
