// The portal over a running local stack. The seeded owner starts a session
// and sends it a message, and the session runner plays the scripted
// provider's answer. The check then records the session's evidence as an
// executor would, since the local stack runs none, and reads the thread, the
// timeline, and the evidence on the session's page. A person of another org
// then finds the session in no list and nothing of it at its address.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test, type Browser, type Page } from "@playwright/test";

const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
const OWNER = process.env.SEED_EMAIL ?? "owner@example.test";
const SLUG = process.env.SEED_SLUG ?? "ajax";
const ORG = process.env.SEED_ORG ?? "Ajax";
const KIND = process.env.ACME_E2E_KIND ?? "platform_assistant";

/** Signs in by address on the local stack; a person in several orgs picks
 *  from the chooser. */
async function signedIn(browser: Browser, email: string, org?: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/login/dev");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Name (for a new person)").fill(email.split("@")[0]!);
  await page.getByRole("button", { name: "Sign in" }).click();
  if (org) await page.getByRole("menuitem", { name: new RegExp(`^${org}\\b`) }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
  return page;
}

function recordEvidence(sessionId: string): void {
  execFileSync("uv", ["run", "--package", "acme-api", "python", "services/api/tests/portal_check.py", "evidence", SLUG, sessionId], {
    cwd: ROOT,
    stdio: "inherit",
  });
}

test("a member starts a session and reads its thread, timeline, and evidence; another org sees none of it", async ({ browser }) => {
  const owner = await signedIn(browser, OWNER, ORG);
  await owner.getByRole("link", { name: "The org's agent sessions" }).click();
  const title = `Tidy the docs ${Date.now()}`;
  await owner.getByLabel("Title").fill(title);
  await owner.getByLabel("Kind").fill(KIND);
  await owner.getByRole("button", { name: "Start", exact: true }).click();
  await expect(owner.getByRole("heading", { level: 1, name: title })).toBeVisible();
  const sessionId = new URL(owner.url()).pathname.split("/").pop()!;

  await owner.getByRole("textbox", { name: "Message", exact: true }).fill("Tidy the docs, please.");
  await owner.getByRole("button", { name: "Send", exact: true }).click();
  const answer = owner.getByRole("list", { name: "Messages" }).locator("[data-who='agent']");
  await expect(answer).toContainText("one voice", { timeout: 90_000 });
  await expect(answer.locator("strong")).toHaveText("one voice");

  recordEvidence(sessionId);

  await owner.getByRole("radio", { name: "Timeline", exact: true }).click();
  const steps = owner.getByRole("list", { name: "Steps" });
  await expect(steps).toContainText("Message from a person");
  await expect(steps).toContainText("Model answered");
  await expect(steps).toContainText("Loop ended");
  console.log(`timeline: ${(await steps.locator("[data-title]").allTextContents()).join(" | ")}`);
  await owner.screenshot({ path: `${SHOTS}session-timeline.png`, fullPage: true });

  await owner.getByRole("radio", { name: "Evidence", exact: true }).click();
  const runs = owner.getByRole("table", { name: "Runs" });
  await expect(runs.locator("tbody tr")).toHaveCount(3);
  await expect(runs).toContainText("twin, never reported as real");
  console.log(`runs: ${(await runs.locator("tbody tr").allTextContents()).join(" | ")}`);
  await expect(owner.getByRole("list", { name: "Validations" }).locator("li")).toHaveCount(1);
  await owner.screenshot({ path: `${SHOTS}session-evidence.png`, fullPage: true });

  const stranger = await signedIn(browser, `stranger-${Date.now()}@example.test`);
  await stranger.goto("/sessions");
  await expect(stranger.getByRole("table", { name: "Sessions" })).toContainText("No sessions yet.");
  await stranger.goto(`/sessions/${sessionId}?tab=timeline`);
  await expect(stranger.getByRole("heading", { level: 1 })).toHaveText("No session here");
  await expect(stranger.getByText(title)).toHaveCount(0);
  console.log(`another org at /sessions/${sessionId}: ${await stranger.getByRole("heading", { level: 1 }).textContent()}`);
});
