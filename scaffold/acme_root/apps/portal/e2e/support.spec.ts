// The support dock beside a parked session, on the stack the timeline check
// runs (`portal_stack.py`), with the scripted provider playing the support
// scene (`portal_check.py script <path> --scene support`): the platform
// assistant searches its corpus, then answers with a link to a page of the
// portal and a link to another site. `portal_check.py tree` writes the
// parked session. "?" opens the dock, the session's pane folds to its rail,
// Send stays open while the assistant works, the answer's portal link is a
// chip that opens its page in the main area while the dock keeps the
// conversation, and the other link is text. Expanded, and as a sheet under
// 1100 pixels, it is shot light and dark under e2e/screenshots/.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { ORG, OWNER, signedIn, SLUG } from "./signIn";

const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
// What `portal_check.py tree` and the support scene write.
const ASKED = "Read every date in the app day first";
const ANSWER = "It waits on its two sub-agents";

test.use({ viewport: { width: 1440, height: 900 } });

async function shoot(page: Page, name: string): Promise<void> {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.screenshot({ path: `${SHOTS}support-${name}-${scheme}.png`, animations: "disabled" });
  }
  await page.emulateMedia({ colorScheme: "light" });
}

type Box = { x: number; y: number; width: number; height: number };

/** Whether two boxes sit side by side, sharing no column. */
function beside(a: Box, b: Box): boolean {
  return a.x + a.width <= b.x + 1 || b.x + b.width <= a.x + 1;
}

/** The parked session's tree; its root's id. */
function parkedRoot(): string {
  const printed = execFileSync("uv", ["run", "--package", "acme-api", "python", "services/api/tests/portal_check.py", "tree", SLUG], {
    cwd: ROOT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
  });
  return (JSON.parse(printed.trim().split("\n").pop()!) as { root: string }).root;
}

test("support beside a parked session: the pane folds first, Send stays open while it works, and a chip opens its page while the dock keeps the conversation", async ({ browser }) => {
  const root = parkedRoot();
  const owner = await signedIn(browser, OWNER, ORG);
  await owner.goto(`/sessions/${root}`);
  await expect(owner.getByRole("heading", { level: 1, name: ASKED })).toBeVisible();
  await expect(owner.locator(".acme-status-pill")).toHaveText("parked");
  const pane = owner.getByRole("complementary", { name: "Session pane" });
  if (!(await pane.isVisible())) await owner.getByRole("button", { name: "Show the panel" }).click();
  await expect(pane).toBeVisible();
  await shoot(owner, "session-before");

  // "?" beside the user chip opens the dock; the session's pane folds to its
  // rail, and the story keeps its minimum in its own column.
  await owner.getByRole("button", { name: "Ask support" }).click();
  const dock = owner.getByRole("complementary", { name: "Support" });
  await expect(dock).toHaveAttribute("data-mode", "side");
  await expect(pane).toHaveAttribute("data-rail", "");
  const story = owner.getByRole("region", { name: "Session" });
  const [storyBox, dockBox, paneBox] = await Promise.all([story.boundingBox(), dock.boundingBox(), pane.boundingBox()]);
  expect(storyBox!.width).toBeGreaterThanOrEqual(360);
  expect(beside(storyBox!, dockBox!), "the story and the dock share no column").toBe(true);
  expect(beside(paneBox!, dockBox!), "the pane and the dock share no column").toBe(true);
  console.log(`story ${Math.round(storyBox!.width)}px · rail ${Math.round(paneBox!.width)}px · dock ${Math.round(dockBox!.width)}px`);
  await shoot(owner, "dock-beside-session");

  // A rail icon shows its view over the story's edge, and folds it again.
  const rail = pane.getByRole("toolbar", { name: "The session's views" });
  await rail.getByRole("button").first().click();
  await expect(pane.locator(".acme-pane-peek")).toBeVisible();
  await shoot(owner, "pane-rail-open");
  await rail.getByRole("button").first().click();
  await expect(pane.locator(".acme-pane-peek")).toHaveCount(0);

  // A question, with the page as data; Send stays open while it works.
  const field = dock.getByRole("textbox", { name: "Ask support" });
  const send = dock.getByRole("button", { name: "Send" });
  await field.fill("Why is this session parked?");
  await send.click();
  await expect(field).toHaveValue("");
  const works = dock.getByText("Working: send at any time");
  await expect(works).toBeVisible();
  await field.fill("And how long will it wait?");
  await expect(send).toBeEnabled();
  console.log(`while it works: Send enabled ${await send.isEnabled()} · still working ${await works.isVisible()}`);
  await shoot(owner, "dock-working");
  await field.fill("");

  // The answer: a chip for the portal's page, text for the other site.
  const chip = dock.locator("button.acme-link-chip", { hasText: "all sessions" });
  await expect(chip).toBeVisible();
  await expect(dock).toContainText(ANSWER);
  await expect(dock).toContainText("platform guide (https://example.com/guide)");
  await expect(dock.locator("a[href^='http']")).toHaveCount(0);
  await expect(dock.getByText(`Sent from /sessions/${root}`)).toBeVisible();
  await expect(dock.locator(".acme-call[data-tool='search_corpus']")).toBeVisible();
  console.log(`chip: ${await chip.innerText()} -> ${await chip.getAttribute("title")}`);
  await shoot(owner, "dock-chip");

  // The chip opens its page in the main area; the dock keeps the conversation.
  await chip.click();
  await expect(owner).toHaveURL(/\/sessions$/);
  await expect(owner.getByRole("heading", { level: 1, name: "All sessions" })).toBeVisible();
  await expect(dock).toHaveAttribute("data-mode", "side");
  await expect(dock).toContainText(ANSWER);
  await shoot(owner, "chip-opened");

  // Expanded, the chat takes the page's width; back beside the page.
  await dock.getByRole("button", { name: "Expand" }).click();
  await expect(dock).toHaveAttribute("data-mode", "expanded");
  await expect(owner.locator(".acme-main")).toBeHidden();
  await shoot(owner, "dock-expanded");
  await dock.getByRole("button", { name: "Back beside the page" }).click();
  await expect(dock).toHaveAttribute("data-mode", "side");

  // Under 1100 pixels the dock is a sheet over the page; its chip closes it
  // and shows the page, and "?" opens it again with the conversation.
  await owner.goBack();
  await expect(owner.getByRole("heading", { level: 1, name: ASKED })).toBeVisible();
  await owner.setViewportSize({ width: 1000, height: 900 });
  await expect(dock).toHaveAttribute("data-mode", "sheet");
  await expect(pane).not.toHaveAttribute("data-rail", "");
  await shoot(owner, "dock-sheet");
  await chip.click();
  await expect(dock).toHaveCount(0);
  await expect(owner.getByRole("heading", { level: 1, name: "All sessions" })).toBeVisible();
  await owner.getByRole("button", { name: "Ask support" }).click();
  await expect(dock).toContainText(ANSWER);

  // Esc closes it.
  await field.press("Escape");
  await expect(dock).toHaveCount(0);
});
