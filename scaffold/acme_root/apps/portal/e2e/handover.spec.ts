// A hand-over's way out, on the stack the sessions check runs. The owner
// starts a session on Home, lets its run end, shares it with the org, and
// takes control in the Workspace view: the card that holds the environment
// offers End this run beside Give it back. The seeded member, on the same
// session, sees who holds it and End this run, never Run or Give it back.
// The owner ends the run there, which cancels the loop as a cancel ends any
// park: the card goes, and the timeline says the run ended cancelled. Each
// card is shot light and dark under e2e/screenshots/.
import { expect, test, type Page } from "@playwright/test";
import { ORG, OWNER, signedIn } from "./signIn";

// The agent the composer's chip offers for the kind the stack registers.
const AGENT = process.env.ACME_E2E_AGENT ?? "Platform assistant";
const MEMBER = process.env.SEED_MEMBER_EMAIL ?? "bob@example.test";
const HOLDS = `${process.env.SEED_NAME ?? "Local Owner"} has control`;
const SHOTS = new URL("./screenshots/", import.meta.url).pathname;

async function shoot(page: Page, name: string): Promise<void> {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.screenshot({ path: `${SHOTS}handover-${name}-${scheme}.png`, animations: "disabled" });
  }
  await page.emulateMedia({ colorScheme: "light" });
}

/** Every member of the org sees the session from here, as its steerer may say
 *  over the API; the portal has no control for it. */
async function shareWithOrg(page: Page, sessionId: string): Promise<void> {
  const status = await page.evaluate(async (id) => {
    const { state } = JSON.parse(sessionStorage.getItem("acme.portal.session")!) as { state: { token: string } };
    const answer = await fetch(`/v1/agent-sessions/${id}/visibility`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${state.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ visibility: "org_wide" }),
    });
    return answer.status;
  }, sessionId);
  expect(status).toBe(200);
}

test("a hand-over: its holder ends the run beside Give it back, another member sees who holds it and End this run alone, and the loop ends cancelled", async ({ browser }) => {
  const owner = await signedIn(browser, OWNER, ORG);
  const title = `Hand over ${Date.now()}`;
  await owner.getByRole("button", { name: /^Agent:/ }).click();
  await owner.getByRole("menuitemradio", { name: new RegExp(`^${AGENT}`) }).click();
  await owner.keyboard.press("Escape");
  await owner.getByRole("textbox", { name: "Prompt" }).fill(title);
  await owner.getByRole("button", { name: "Send", exact: true }).click();
  await expect(owner.getByRole("heading", { level: 1, name: title })).toBeVisible();
  const sessionId = new URL(owner.url()).pathname.split("/").pop()!;
  const chat = owner.getByRole("list", { name: "Timeline" });
  await expect(chat.locator("[data-kind='line']").last()).toContainText("Run ended: succeeded", { timeout: 90_000 });
  await shareWithOrg(owner, sessionId);

  const pane = owner.getByRole("complementary", { name: "Session pane" });
  await pane.getByRole("tab", { name: "Workspace" }).click();
  await pane.getByRole("button", { name: "Take control", exact: true }).click();
  const card = pane.locator("section#control");
  await expect(card.getByRole("heading", { name: "You have control" })).toBeVisible();
  // Beside it: the give-back form holds both.
  const giveBack = card.getByRole("form", { name: "Give it back" });
  await expect(giveBack.getByRole("button", { name: "Give it back", exact: true })).toBeVisible();
  const end = giveBack.getByRole("button", { name: "End this run", exact: true });
  await expect(end).toBeVisible();
  console.log(`the holder's card: ${(await card.getByRole("button").allInnerTexts()).join(" | ")}`);
  await shoot(owner, "card");

  // Another member who may write: who holds it, and the end of the run alone.
  const member = await signedIn(browser, MEMBER, ORG);
  await member.goto(`/sessions/${sessionId}?pane=workspace`);
  const theirs = member.getByRole("complementary", { name: "Session pane" }).locator("section#control");
  await expect(theirs.getByRole("heading", { name: HOLDS })).toBeVisible();
  await expect(theirs.getByRole("button", { name: "End this run", exact: true })).toBeVisible();
  await expect(member.getByRole("form", { name: "Run a command" })).toHaveCount(0);
  await expect(member.getByRole("form", { name: "Give it back" })).toHaveCount(0);
  await expect(member.getByRole("button", { name: "Give it back", exact: true })).toHaveCount(0);
  console.log(`another member's card: ${await theirs.getByRole("heading").innerText()} | ${(await theirs.getByRole("button").allInnerTexts()).join(" | ")}`);
  await shoot(member, "held-by-another");

  await end.click();
  await expect(card.getByRole("heading", { name: "You have control" })).toHaveCount(0);
  await expect(chat.locator("[data-kind='line']").last()).toContainText("Run ended: cancelled", { timeout: 60_000 });
  await expect(pane.getByRole("button", { name: "Take control", exact: true })).toBeVisible();
  await expect(theirs.getByRole("heading", { name: HOLDS })).toHaveCount(0);
  console.log(`after End this run: ${await chat.locator("[data-kind='line']").last().innerText()}`);
  await shoot(owner, "cancelled");
});
