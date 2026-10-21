// Sharing over a running local stack, on the sharing script (two turns).
// The platform assistant runs on its person's own permissions, so its
// sessions start private. The seeded owner starts one and makes it
// org-wide; the seeded member starts one and keeps it private. In
// Sessions, the member's own view holds theirs; the org's view holds the
// owner's, which the member joins, and never the member's private one. In
// the session the member
// writes a suggestion, since the owner steers it. The owner, whose role
// sees every session for an audit, reads the private one in the API's
// answer and never on the org's view; on the session's page the owner reads
// the member's suggestion and hands the steer to them, and the page then
// says the member steers.
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { MEMBER, mintLogins, ORG, OWNER, signedIn } from "./signIn";

const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
const MEMBER_NAME = process.env.SEED_MEMBER_NAME ?? "Bob";
const OWNER_NAME = process.env.SEED_NAME ?? "Local Owner";
// The agent the composer's chip offers for the kind the stack registers.
const AGENT = process.env.ACME_E2E_AGENT ?? "Platform assistant";
const STAMP = Date.now();

/** Starts a session on Home, waits for its answer, and gives its id. */
async function start(page: Page, title: string): Promise<string> {
  await page.goto("/");
  await page.getByRole("button", { name: /^Agent:/ }).click();
  await page.getByRole("menuitemradio", { name: new RegExp(`^${AGENT}`) }).click();
  await page.keyboard.press("Escape");
  await page.getByRole("textbox", { name: "Prompt" }).fill(`${title}\nKeep the voice plain.`);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  await expect(page.getByRole("list", { name: "Timeline" }).locator("[data-kind='prose']")).toContainText("one voice", { timeout: 90_000 });
  return new URL(page.url()).pathname.split("/").pop()!;
}

/** Dismisses every notice on show, so a screenshot shows the page under it. */
async function quiet(page: Page): Promise<void> {
  const dismiss = page.getByRole("button", { name: "dismiss" });
  while ((await dismiss.count()) > 0) await dismiss.first().click();
}

const chip = (page: Page) => page.locator(".acme-sharing-chip");
const panel = (page: Page) => page.getByRole("dialog", { name: "Who steers and who sees this session" });
const rows = (page: Page, table: string) => page.getByRole("table", { name: table }).locator("tbody tr");

test("a member finds the org's sessions and joins one, suggests in it, and its steerer hands them the steer; a private one stays out of the org's view", async ({ browser }) => {
  const logins = mintLogins(OWNER, MEMBER);
  const owner = await signedIn(browser, logins, OWNER, ORG);
  const team = `Release notes ${STAMP}`;
  const teamId = await start(owner, team);
  await expect(chip(owner)).toHaveText("You steer");
  await expect(chip(owner)).toHaveAttribute("title", "You steer. Private.");
  await chip(owner).click();
  await panel(owner).getByRole("button", { name: "Make it org-wide" }).click();
  await expect(chip(owner)).toHaveAttribute("title", "You steer. Org-wide.");
  await expect(owner.getByRole("list", { name: "Timeline" }).locator("[data-kind='shared']")).toContainText("Made org-wide");

  const member = await signedIn(browser, logins, MEMBER, ORG);
  const draft = `Salary notes ${STAMP}`;
  const draftId = await start(member, draft);
  await expect(chip(member)).toHaveAttribute("title", "You steer. Private.");

  // The member's own view, then the org's: theirs is private, the owner's is there to join.
  await member.goto("/sessions");
  await expect(member.getByRole("heading", { level: 1, name: "Sessions" })).toBeVisible();
  await expect(rows(member, "Your sessions").filter({ hasText: draft })).toContainText("Private");
  await expect(rows(member, "Your sessions").filter({ hasText: team })).toHaveCount(0);
  console.log(`member, yours: ${(await rows(member, "Your sessions").allInnerTexts()).filter((row) => row.includes(String(STAMP))).join(" | ")}`);
  await member.getByRole("radio", { name: "The org's" }).click();
  const teamRow = rows(member, "The org's sessions").filter({ hasText: team });
  await expect(teamRow).toContainText(OWNER_NAME);
  await expect(rows(member, "The org's sessions").filter({ hasText: draft })).toHaveCount(0);
  await quiet(member);
  await member.screenshot({ path: `${SHOTS}sharing-org-view.png`, animations: "disabled" });
  await teamRow.getByRole("button", { name: "Join" }).click();
  await expect(teamRow).toContainText("Joined");
  console.log(`member, the org's: ${(await rows(member, "The org's sessions").allInnerTexts()).filter((row) => row.includes(String(STAMP))).join(" | ")}`);
  await member.getByRole("radio", { name: "Yours" }).click();
  await expect(rows(member, "Your sessions").filter({ hasText: team })).toContainText("joined");
  await quiet(member);
  await member.screenshot({ path: `${SHOTS}sharing-yours.png`, animations: "disabled" });

  // In the session, the member suggests: the owner steers it.
  await member.goto(`/sessions/${teamId}`);
  await expect(chip(member)).toHaveText(`${OWNER_NAME} steers`);
  const composer = member.getByRole("textbox", { name: "Suggestion" });
  await expect(composer).toHaveAttribute("placeholder", `Suggest something to ${OWNER_NAME}, who steers it`);
  await composer.fill("Lead with the breaking change.");
  await member.getByRole("button", { name: "Send", exact: true }).click();
  const memberChat = member.getByRole("list", { name: "Timeline" });
  await expect(memberChat.locator(".acme-bubble[data-suggestion]")).toContainText("Your suggestion");

  // The owner sees every session for an audit; the org's view shows none private.
  const listed = owner.waitForResponse((response) => response.url().includes("among=visible"));
  await owner.goto("/sessions?view=org");
  const answered = (await (await listed).json()) as { items: { id: string; visibility: string }[] };
  expect(answered.items.find((item) => item.id === draftId)?.visibility).toBe("private");
  await expect(rows(owner, "The org's sessions").filter({ hasText: team })).toContainText("Yours");
  await expect(owner.getByText(draft)).toHaveCount(0);
  console.log(`owner: the API listed ${draft} (private); the org's view shows ${await owner.getByText(draft).count()} rows of it`);

  // The owner reads the suggestion and hands the steer to the member.
  await owner.goto(`/sessions/${teamId}`);
  const ownerChat = owner.getByRole("list", { name: "Timeline" });
  await expect(ownerChat.locator(".acme-bubble[data-suggestion]")).toContainText(`Suggestion from ${MEMBER_NAME}`);
  await quiet(owner);
  await chip(owner).click();
  await panel(owner).getByLabel("Hand the steer to").selectOption({ label: MEMBER_NAME });
  await expect(panel(owner)).toBeVisible();
  await owner.screenshot({ path: `${SHOTS}sharing-hand-off.png`, animations: "disabled" });
  await panel(owner).getByRole("button", { name: "Hand it over" }).click();
  await expect(chip(owner)).toHaveText(`${MEMBER_NAME} steers`);
  await expect(ownerChat.locator("[data-kind='shared']").last()).toContainText(`${MEMBER_NAME} steers it from here`);
  await expect(owner.getByRole("textbox", { name: "Suggestion" })).toHaveAttribute("placeholder", `Suggest something to ${MEMBER_NAME}, who steers it`);
  await quiet(owner);
  await owner.screenshot({ path: `${SHOTS}sharing-steered.png`, animations: "disabled" });
  console.log(`owner after the hand-off: ${await chip(owner).innerText()} | ${await ownerChat.locator("[data-kind='shared']").last().innerText()}`);

  // The member's page says so too.
  await member.reload();
  await expect(chip(member)).toHaveText("You steer");
});
