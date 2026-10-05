// The portal over a running local stack. The seeded owner describes a task
// on Home and sends it; the session opens, and the left bar shows it under
// Running while the session runner plays the scripted provider's answer
// (paced, so the run stays open to be seen), then under Recent. The check
// records the session's evidence as an executor would, since the local stack
// runs none, and reads the thread, the timeline, and the evidence on the
// session's page. A person of another org then finds no row of it in the
// left bar or in All sessions, and nothing of it at its address.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { ORG, OWNER, signedIn, SLUG } from "./signIn";

const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
// The agent the composer's chip offers for the kind the stack registers.
const AGENT = process.env.ACME_E2E_AGENT ?? "Platform assistant";

function recordEvidence(sessionId: string): void {
  execFileSync("uv", ["run", "--package", "acme-api", "python", "services/api/tests/portal_check.py", "evidence", SLUG, sessionId], {
    cwd: ROOT,
    stdio: "inherit",
  });
}

test("a member starts a session on Home, sees it run and finish in the left bar, and reads it; another org sees no row of it", async ({ browser }) => {
  const owner = await signedIn(browser, OWNER, ORG);
  const title = `Tidy the docs ${Date.now()}`;
  await owner.getByRole("button", { name: /^Agent:/ }).click();
  await owner.getByRole("menuitemradio", { name: new RegExp(`^${AGENT}`) }).click();
  await owner.keyboard.press("Escape");
  await expect(owner.getByRole("button", { name: `Agent: ${AGENT}` })).toBeVisible();
  await owner.getByRole("textbox", { name: "Prompt" }).fill(`${title}\nKeep the voice plain.`);
  await owner.getByRole("button", { name: "Send", exact: true }).click();
  await expect(owner.getByRole("heading", { level: 1, name: title })).toBeVisible();
  const sessionId = new URL(owner.url()).pathname.split("/").pop()!;

  const bar = owner.getByRole("complementary", { name: "Sidebar" });
  await expect(bar.getByRole("list", { name: "Running" })).toContainText(title);
  console.log(`running: ${await bar.getByRole("list", { name: "Running" }).innerText()}`);
  await owner.screenshot({ path: `${SHOTS}shell-running.png` });

  const answer = owner.getByRole("list", { name: "Messages" }).locator("[data-who='agent']");
  await expect(answer).toContainText("one voice", { timeout: 90_000 });
  await expect(answer.locator("strong")).toHaveText("one voice");
  await expect(bar.getByRole("list", { name: "Recent" })).toContainText(title);
  await expect(bar.getByRole("list", { name: "Running" })).toHaveCount(0);
  console.log(`recent: ${(await bar.getByRole("list", { name: "Recent" }).innerText()).split("\n").slice(0, 3).join(" | ")}`);

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
  const strangerBar = stranger.getByRole("complementary", { name: "Sidebar" });
  await expect(strangerBar).toContainText("No sessions yet. Describe a task on Home.");
  await expect(strangerBar.getByText(title)).toHaveCount(0);
  console.log(`another org's left bar: ${(await strangerBar.locator(".acme-sidebar-scroll").innerText()).trim()}`);
  await stranger.goto("/sessions");
  await expect(stranger.getByRole("heading", { level: 1, name: "All sessions" })).toBeVisible();
  await expect(stranger.getByRole("main").getByText("No sessions yet.")).toBeVisible();
  await stranger.goto(`/sessions/${sessionId}?tab=timeline`);
  await expect(stranger.getByRole("heading", { level: 1 })).toHaveText("No session here");
  await expect(stranger.getByText(title)).toHaveCount(0);
  console.log(`another org at /sessions/${sessionId}: ${await stranger.getByRole("heading", { level: 1 }).textContent()}`);
});
