// What the browser checks share: the stack's seeded people and org, and a
// sign-in from the local mint. No page signs anyone in. `acme-api
// mint-local-login` prints a login for each person a check needs, in one
// process on the local database; the API exchanges each for an auth session
// in the org, as the portal does once the identity provider sends a person
// back; and the session goes where the portal keeps it, in the tab's session
// storage, before the page loads.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, type Browser, type Page } from "@playwright/test";

const ROOT = fileURLToPath(new URL("../../..", import.meta.url));

/** A seed knob as `make seed` reads it: the shell, then `.env`, then
 *  `.env.example`, each line read as dotenv reads it (an inline comment and
 *  one layer of quotes dropped). */
function seedSetting(name: string): string | undefined {
  if (process.env[name]) return process.env[name];
  for (const file of [".env", ".env.example"]) {
    const path = `${ROOT}/${file}`;
    if (!existsSync(path)) continue;
    const line = readFileSync(path, "utf8").split("\n").filter((each) => each.startsWith(`${name}=`)).pop();
    const value = line
      ?.slice(name.length + 1)
      .replace(/\s+#.*$/, "")
      .trim()
      .replace(/^(["'])(.*)\1$/, "$2");
    if (value) return value;
  }
  return undefined;
}

/** The base every seeded address is a plus-address of: SEED_EMAIL, else
 *  git's user.email, as `make seed` takes it. */
const BASE = seedSetting("SEED_EMAIL") ?? execFileSync("git", ["config", "user.email"], { cwd: ROOT, encoding: "utf8" }).trim();

/** A seeded person's address, as `make seed` derives it: the owner's tag is
 *  the org's slug, the member's `personal`. */
function seedAddress(tag: string): string {
  const [local, domain] = BASE.split("@");
  return `${local}+acme+local+${tag}@${domain}`;
}

export const SLUG = seedSetting("SEED_SLUG") ?? "ajax";
export const ORG = seedSetting("SEED_ORG") ?? "Ajax";
export const OWNER = seedAddress(SLUG);
export const MEMBER = seedAddress("personal");

/** Each address's login, from the local mint. */
export type Logins = ReadonlyMap<string, string>;

/** A login for each address: one `acme-api mint-local-login` process for
 *  every person a check signs in. A person nobody holds is made, with their
 *  personal org. A login lasts ten minutes, so a check mints its people when
 *  it starts. */
export function mintLogins(...emails: string[]): Logins {
  const printed = execFileSync(
    "uv",
    ["run", "--package", "acme-api", "acme-api", "mint-local-login", ...emails.flatMap((email) => ["--email", email])],
    { cwd: ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
  );
  const tokens = printed.split("\n").filter((line) => line.startsWith("lgn_"));
  if (tokens.length !== emails.length) throw new Error(`the local mint printed ${tokens.length} logins for ${emails.length} people`);
  return new Map(emails.map((email, at) => [email, tokens[at]!]));
}

/** The key the portal's auth session store persists under (`src/store/authSession.ts`). */
const AUTH_SESSION_STORAGE_KEY = "acme.portal.authSession";

interface Place {
  org: { id: string; name: string; slug: string };
}

/** Signs a person in from their minted login: their places are read, the
 *  one in `org` is chosen (a person in one place needs none), and the auth
 *  session the exchange issues is put in the portal's store before Home
 *  loads. */
export async function signedIn(browser: Browser, logins: Logins, email: string, org?: string): Promise<Page> {
  const login = logins.get(email);
  if (!login) throw new Error(`no login was minted for ${email}`);
  const context = await browser.newContext();
  const headers = { Authorization: `Bearer ${login}`, "X-App": "portal", "X-App-Version": "portal@e2e" };
  const places = await context.request.get("/v1/auth/memberships?limit=100", { headers });
  expect(places.ok(), await places.text()).toBe(true);
  const items = ((await places.json()) as { items: Place[] }).items;
  const place = org ? items.find((each) => each.org.name === org) : items.length === 1 ? items[0] : undefined;
  if (!place) throw new Error(`${email} holds no place ${org ? `in ${org}` : "to go straight into"}`);
  const issued = await context.request.post("/v1/auth/sessions", { headers, data: { org_id: place.org.id } });
  expect(issued.ok(), await issued.text()).toBe(true);
  const session = (await issued.json()) as { token: string; org: { slug: string } };
  const stored = JSON.stringify({ state: { token: session.token, orgSlug: session.org.slug }, version: 0 });
  // Only the first load takes it: a reload keeps whatever the portal holds
  // by then, a switch or a sign-out included.
  await context.addInitScript(
    ([key, value]) => {
      try {
        if (window.sessionStorage.getItem(key) === null) window.sessionStorage.setItem(key, value);
      } catch {
        // A document with no storage of its own, such as about:blank.
      }
    },
    [AUTH_SESSION_STORAGE_KEY, stored] as const,
  );
  const page = await context.newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();
  return page;
}
