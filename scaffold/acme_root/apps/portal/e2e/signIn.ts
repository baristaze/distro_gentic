// What the browser checks share: the stack's seeded owner and org, and a
// sign-in by address on the local stack.
import { expect, type Browser, type Page } from "@playwright/test";

export const OWNER = process.env.SEED_EMAIL ?? "owner@example.test";
export const SLUG = process.env.SEED_SLUG ?? "ajax";
export const ORG = process.env.SEED_ORG ?? "Ajax";

/** Signs in by address on the local stack; a person in several orgs picks
 *  from the chooser. */
export async function signedIn(browser: Browser, email: string, org?: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto("/login/dev");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Name (for a new person)").fill(email.split("@")[0]!);
  await page.getByRole("button", { name: "Sign in" }).click();
  if (org) await page.getByRole("menuitem", { name: new RegExp(`^${org}\\b`) }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
  return page;
}
