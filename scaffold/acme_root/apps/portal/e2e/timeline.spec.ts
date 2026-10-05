// The engineer's scene over a local stack started for it: the API and the
// runner of `services/api/tests/portal_stack.py`, the runner on the scene's
// script (`portal_check.py script <path> --scene engineer`), paced, and the
// forge's twin. The owner starts an engineer on Home and reads its session
// as a chat while it runs: its first thought and words stream in before
// their step lands; its calls fold into work blocks whose lines say what
// ran; its edit opens as a diff; each command it holds waits on an action
// card whose Approve resumes it; its question turns the composer to an answer;
// its plan, pull request, validation, and result read as cards. Each moment
// is shot light and dark under e2e/screenshots/.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { ORG, OWNER, signedIn, SLUG } from "./signIn";

const ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
// The folder the runner clones the org's repository from (`portal_stack.py runner`).
const REPOSITORIES = process.env.PORTAL_REPOSITORIES;
const PROMPT = "Fix the failing test in tests/test_dates.py and open a pull request";

test.use({ viewport: { width: 1440, height: 900 } });

async function shoot(page: Page, name: string): Promise<void> {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    // A scheme's colors ease in: the shot ends each transition first.
    await page.screenshot({ path: `${SHOTS}timeline-${name}-${scheme}.png`, animations: "disabled" });
  }
  await page.emulateMedia({ colorScheme: "light" });
}

/** Approves the call the session holds, shot first when named, and waits
 * until its card is gone. */
async function approve(chat: Locator, shot?: string): Promise<string> {
  const card = chat.getByRole("region", { name: "Action required" });
  await expect(card).toBeVisible({ timeout: 90_000 });
  const held = (await card.locator(".acme-call-gist").innerText()).trim();
  if (shot) await shoot(chat.page(), shot);
  await card.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(card).toHaveCount(0);
  return held;
}

test("the engineer's session reads as a live chat: thoughts, work blocks, a diff, cards, and an approval that resumes it", async ({ browser }) => {
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
  const chat = owner.getByRole("list", { name: "Timeline" });

  // The first thought streams in open, and the words after it carry a caret,
  // before the model's step is stored.
  const thinking = chat.locator(".acme-thought[data-live]");
  await expect(thinking).toBeVisible({ timeout: 60_000 });
  await expect(thinking).toContainText("Thinking…");
  console.log(`streaming: ${(await thinking.innerText()).split("\n").slice(0, 2).join(" | ")}`);
  await shoot(owner, "mid-thought");
  // A pause from the header, sent while it streams, parks it at its next
  // step; Resume in the header takes it on.
  const header = owner.locator(".acme-session-head");
  await header.getByRole("button", { name: "Pause", exact: true }).click();
  const streamed = chat.locator(".acme-prose[data-live]");
  await expect(streamed).toBeVisible();
  await expect(streamed.locator(".acme-caret")).toBeVisible();
  // The step lands and takes the stream's place: the thought folds, timed.
  await expect(chat.locator(".acme-thought").first()).toContainText(/Thought for \d+s/);
  await expect(chat.locator(".acme-prose[data-live]")).toHaveCount(0, { timeout: 30_000 });
  await expect(chat.getByRole("region", { name: "Plan" })).toContainText("Run tests/test_dates.py and see it fail.");
  const resume = header.getByRole("button", { name: "Resume", exact: true });
  await expect(resume).toBeVisible({ timeout: 30_000 });
  await expect(chat.getByRole("status")).toContainText(/paused/i);
  await shoot(owner, "park");
  await resume.click();
  await expect(resume).toHaveCount(0);

  // Its plan's answer, a tool's output, marks it, so each command it runs
  // under open egress waits on an action card, and Approve resumes it: the
  // command runs and folds into a work block whose lines say what ran, the
  // second command follows the first, and its pull request the second.
  const first = await approve(chat, "action");
  console.log(`approved: ${first}`);
  expect(first).toContain("tests/test_dates.py");
  const blocks = chat.locator(".acme-work");
  await expect(blocks.first()).toBeVisible();
  const second = await approve(chat);
  console.log(`approved: ${second}`);
  expect(second).toContain("sh -c");
  const pull = chat.getByRole("region", { name: "Pull request" });
  await expect(pull).toContainText("Read a date day first", { timeout: 60_000 });
  console.log(`pull request: ${(await pull.innerText()).split("\n").join(" | ")}`);

  // The question parks it; the composer turns to an answer.
  const asks = chat.getByRole("region", { name: "The agent asks" });
  await expect(asks).toContainText("leap day", { timeout: 60_000 });
  const answer = owner.getByRole("textbox", { name: "Answer" });
  await expect(answer).toHaveAttribute("placeholder", "Answer the agent's question");
  await expect(chat.getByRole("status")).toHaveText("Needs you: answer the agent's question");
  await shoot(owner, "ask");

  // Every block folded once its calls are done; a line opens its answer inline.
  const lines = await blocks.locator(".acme-fold-line").allInnerTexts();
  console.log(`blocks: ${lines.join(" | ")}`);
  expect(lines.every((line) => /^Worked for \S+( \S+)? · \d+ steps?$/.test(line))).toBe(true);
  await shoot(owner, "folded");
  for (const block of await blocks.all()) await block.locator(".acme-fold-line").first().click();
  const failed = chat.locator(".acme-call", { hasText: "Ran python3 tests/test_dates.py · exit 1" });
  await expect(failed).toBeVisible();
  const edit = chat.locator(".acme-call", { hasText: "Edited src/dates.py +1 −1" });
  await edit.locator(".acme-call-line").click();
  await expect(edit.locator(".acme-call-body")).toContainText("day, month, year");
  await edit.scrollIntoViewIfNeeded();
  await shoot(owner, "block-open");

  await answer.fill("Not now, thanks.");
  await owner.getByRole("button", { name: "Send", exact: true }).click();
  await expect(asks).toContainText("Answered.");
  console.log(`approved: ${await approve(chat)}`);

  const result = chat.getByRole("region", { name: "Result" });
  await expect(result).toContainText("claims succeeded", { timeout: 90_000 });
  await expect(chat.getByRole("region", { name: "Validation" })).toBeVisible();
  await expect(chat.getByRole("status")).toHaveText("Done", { timeout: 60_000 });
  await expect(owner.locator(".acme-pr-badge")).toHaveText(/^#\d+$/);
  console.log(`cards: ${(await chat.locator(".acme-tcard").evaluateAll((cards) => cards.map((card) => card.getAttribute("data-card")))).join(", ")}`);
  console.log(`status: ${await chat.getByRole("status").innerText()}`);
  await shoot(owner, "cards");
  // Each card on its own, in view.
  for (const card of ["plan", "pull_request", "validation", "result"]) {
    await chat.locator(`.acme-tcard[data-card="${card}"]`).first().scrollIntoViewIfNeeded();
    await shoot(owner, `card-${card.replace("_", "-")}`);
  }
});
