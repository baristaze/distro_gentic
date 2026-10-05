// A session's right pane over the engineer's scene, on the stack the
// timeline check runs (`portal_stack.py`, the scene's script, the forge's
// twin). The owner starts an engineer on Home: Workspace opens itself
// while it runs, and Changes once it delivers. A line of a work block opens
// its step; "+" opens the rest. Then the owner takes control, runs
// `pytest -q` on the host that holds its workspace (`portal_check.py host`
// stands in for it), and gives it back: the agent reads what they did and
// validates the head again.
// The pane hides and shows again on Option-Cmd-B. Each view is shot light
// and dark under e2e/screenshots/.
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { ORG, OWNER, signedIn, SLUG } from "./signIn";

const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
// The folder the runner clones the org's repository from (`portal_stack.py runner`).
const REPOSITORIES = process.env.PORTAL_REPOSITORIES;
// The API the stand-in host claims a person's command from.
const API = process.env.PORTAL_API_URL;
const PROMPT = "Fix the failing test in tests/test_dates.py and open a pull request";

test.use({ viewport: { width: 1440, height: 900 } });

async function shoot(page: Page, name: string): Promise<void> {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.screenshot({ path: `${SHOTS}pane-${name}-${scheme}.png`, animations: "disabled" });
  }
  await page.emulateMedia({ colorScheme: "light" });
}

function check(...args: string[]): void {
  execFileSync("uv", ["run", "--package", "acme-api", "python", "services/api/tests/portal_check.py", ...args], { cwd: ROOT, stdio: "inherit" });
}

/** Approves the call the session holds and waits until its card is gone. */
async function approve(chat: Locator): Promise<void> {
  const card = chat.getByRole("region", { name: "Action required" });
  await expect(card).toBeVisible({ timeout: 90_000 });
  await card.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(card).toHaveCount(0);
}

test("a session's pane: tabs that open themselves once, a step from its row, and take control that runs pytest and gives back", async ({ browser }) => {
  test.skip(!REPOSITORIES || !API, "PORTAL_REPOSITORIES names the scene's repositories, PORTAL_API_URL the API");
  check("scene", REPOSITORIES!, SLUG);
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
  const pane = owner.getByRole("complementary", { name: "Session pane" });
  const tabs = pane.getByRole("tablist", { name: "The session's views" });
  const tabNames = async () => (await tabs.getByRole("tab").allInnerTexts()).map((name) => name.trim());

  // While it runs, Workspace opens itself.
  await expect(pane.getByRole("tab", { name: "Workspace" })).toHaveAttribute("aria-selected", "true", { timeout: 60_000 });
  expect(new URL(owner.url()).searchParams.get("pane")).toBe("workspace");

  // The scene: two commands, its pull request, its question, its validation.
  await approve(chat);
  await approve(chat);
  await expect(chat.getByRole("region", { name: "Pull request" })).toContainText("Read a date day first", { timeout: 60_000 });
  // Once it delivers, Changes opens itself.
  await expect(pane.getByRole("tab", { name: "Changes" })).toHaveAttribute("aria-selected", "true");
  await expect(chat.getByRole("region", { name: "The agent asks" })).toContainText("leap day", { timeout: 60_000 });
  await owner.getByRole("textbox", { name: "Answer" }).fill("Not now, thanks.");
  await owner.getByRole("button", { name: "Send", exact: true }).click();
  await approve(chat);
  await expect(chat.getByRole("status")).toHaveText("Done", { timeout: 90_000 });
  console.log(`opened themselves: ${(await tabNames()).join(", ")}`);
  expect(await tabNames()).toEqual(["Workspace", "Changes"]);
  await expect(pane.getByRole("list", { name: "Changed files" })).toContainText("src/dates.py");
  await expect(pane.getByRole("list", { name: "Changed files" })).toContainText("+1 −1");
  await shoot(owner, "three-panes");
  await shoot(owner, "tab-changes");

  // A line of a work block opens its step. Every block is folded once done,
  // and the first holds the scene's spawns, so each opens.
  const blocks = chat.locator(".acme-work");
  for (const block of await blocks.all()) await block.locator(".acme-fold-line").first().click();
  const failed = chat.locator(".acme-call", { hasText: "Ran python3 tests/test_dates.py · exit 1" });
  await failed.locator(".acme-call-line").click();
  await expect(pane.getByRole("tab", { name: "Step" })).toHaveAttribute("aria-selected", "true");
  const step = pane.getByRole("region", { name: "Step" });
  await expect(step).toContainText("run_command");
  await expect(step).toContainText("Approved by a person");
  await expect(step).toContainText("the month is the second part");
  expect(new URL(owner.url()).searchParams.get("pane")).toBe("step");
  console.log(`step: ${(await step.locator(".acme-facts").innerText()).split("\n").join(" | ")}`);
  await shoot(owner, "tab-step");

  // "+" lists the views not open; each opens as a tab.
  await pane.getByRole("button", { name: "Open a view" }).click();
  const offered = await owner.getByRole("menuitem").allInnerTexts();
  console.log(`+ offers: ${offered.map((name) => name.trim()).join(", ")}`);
  expect(offered.map((name) => name.trim())).toEqual(["Evidence", "Plan", "Sub-agents", "Usage"]);
  await shoot(owner, "plus");
  await owner.keyboard.press("Escape");
  for (const [name, holds] of [
    ["Evidence", "Validations"],
    ["Plan", "Run `tests/test_dates.py` and see it fail.".replace(/`/g, "")],
    ["Sub-agents", "Its tree has spawned 2 of the 10 sub-agents it may"],
    ["Usage", "model calls"],
  ] as const) {
    await pane.getByRole("button", { name: "Open a view" }).click();
    await owner.getByRole("menuitem", { name }).click();
    await expect(pane.getByRole("tab", { name })).toHaveAttribute("aria-selected", "true");
    await expect(pane.getByRole("tabpanel")).toContainText(holds);
    await shoot(owner, `tab-${name.toLowerCase().replace("-", "")}`);
  }
  expect(await tabNames()).toEqual(["Workspace", "Changes", "Step", "Evidence", "Plan", "Sub-agents", "Usage"]);
  await expect(pane.getByRole("button", { name: "Open a view" })).toBeDisabled();

  // Take control: a command runs on the host that holds its workspace, and
  // the person gives it back with what they did.
  await pane.getByRole("tab", { name: "Workspace" }).click();
  const host = spawn("uv", ["run", "--package", "acme-api", "python", "services/api/tests/portal_check.py", "host", REPOSITORIES!, SLUG, sessionId, API!], {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "inherit"],
  });
  const hostSaid: string[] = [];
  const hostEnded = new Promise<number | null>((resolve) => host.on("exit", resolve));
  await new Promise<void>((resolve, reject) => {
    host.stdout.on("data", (chunk: Buffer) => {
      hostSaid.push(...chunk.toString().split("\n").filter(Boolean));
      if (hostSaid.includes("ready")) resolve();
    });
    host.on("exit", (code) => reject(new Error(`the stand-in host ended (${code}) before it was ready`)));
  });
  await pane.getByRole("button", { name: "Take control", exact: true }).click();
  const control = pane.getByRole("form", { name: "Run a command" });
  await expect(control).toBeVisible();
  await control.getByRole("textbox", { name: "Command" }).fill("pytest -q");
  await control.getByRole("button", { name: "Run", exact: true }).click();
  const state = pane.locator("[data-command-state]");
  await expect(state).toHaveText("done, exit 0", { timeout: 60_000 });
  const printed = pane.getByRole("log", { name: "Command output" });
  await expect(printed).toContainText("1 passed");
  console.log(`command: ${await state.innerText()} | ${(await printed.innerText()).trim().split("\n").pop()}`);
  console.log(`stand-in host: ${hostSaid.join(" | ")}; ended ${await hostEnded}`);
  await shoot(owner, "tab-workspace-control");
  await pane.getByRole("textbox", { name: "What you did, for the agent to read" }).fill("I ran pytest -q on the branch: 1 passed.");
  await pane.getByRole("button", { name: "Give it back", exact: true }).click();
  await expect(pane.getByRole("form", { name: "Run a command" })).toHaveCount(0);
  await expect(chat.locator("[data-kind='prose']").last()).toContainText("The test passes on the branch", { timeout: 90_000 });
  // It validates the head again, and submits its result again.
  await approve(chat);
  await expect(chat.getByRole("status")).toHaveText("Done", { timeout: 60_000 });
  console.log(`after giving back: ${await chat.getByRole("status").innerText()}`);
  await shoot(owner, "tab-workspace");

  // Option-Cmd-B hides the pane and shows it again where it was.
  await owner.keyboard.press("Alt+Meta+KeyB");
  await expect(pane).toHaveCount(0);
  expect(new URL(owner.url()).searchParams.get("pane")).toBeNull();
  await shoot(owner, "collapsed");
  await owner.keyboard.press("Alt+Meta+KeyB");
  await expect(pane.getByRole("tab", { name: "Workspace" })).toHaveAttribute("aria-selected", "true");

  // A new visit keeps the tabs, and Workspace does not open itself again.
  await pane.getByRole("button", { name: "Close Workspace" }).click();
  await owner.reload();
  await expect(chat.getByRole("status")).toHaveText("Done");
  expect(await tabNames()).toEqual(["Changes", "Step", "Evidence", "Plan", "Sub-agents", "Usage"]);
});
