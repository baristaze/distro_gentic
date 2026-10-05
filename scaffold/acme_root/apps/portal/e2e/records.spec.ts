// The record screens over a running local stack; only the API and this dev
// server need to be up. The seeded owner makes a project through its
// screen and gives its repository a read credential, saves the org's own
// key to a provider (the stack's probe twin takes it, so no provider is
// called), and makes an automation that starts a session in the project.
// Each record is then read back from the API as the owner. The credential's
// password and the key go out once, in their writes: no reply the portal
// reads holds either, and no screen shows either. A person of another org
// then finds none of the records.
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { ORG, OWNER, signedIn } from "./signIn";

const SHOTS = fileURLToPath(new URL("./screenshots/", import.meta.url));
const STAMP = Date.now();
const PASSWORD = `cred-${STAMP}-never-shown`;
const KEY = `key-${STAMP}-never-shown`;

/** Every reply the page reads from the API, by its address, and the
 * bearer the page sends, to read the records back as it would. */
function listen(page: Page) {
  const replies: { url: string; body: string }[] = [];
  let bearer = "";
  page.on("request", (request) => {
    const auth = request.headers()["authorization"];
    if (auth && request.url().includes("/v1/")) bearer = auth;
  });
  page.on("response", async (response) => {
    if (!response.url().includes("/v1/")) return;
    replies.push({ url: response.url(), body: await response.text().catch(() => "") });
  });
  return { replies, bearer: () => bearer };
}

test("an owner keeps a project, a key, and an automation through the screens; the secrets come back nowhere, and another org sees none of it", async ({ browser }) => {
  const owner = await signedIn(browser, OWNER, ORG);
  const seen = listen(owner);
  const readBack = async <T>(path: string): Promise<T> => {
    const response = await owner.request.get(path, { headers: { authorization: seen.bearer() } });
    expect(response.status()).toBe(200);
    const body = await response.text();
    seen.replies.push({ url: path, body });
    return JSON.parse(body) as T;
  };

  // A project bound to its repository, and the repository's read credential.
  await owner.goto("/projects");
  const projectName = `Docs ${STAMP}`;
  const repository = `forge.example.com/acme/docs-${STAMP}`;
  await owner.getByLabel("Name").fill(projectName);
  await owner.getByLabel("Repository").fill(`https://${repository}.git`);
  await owner.getByRole("button", { name: "Make the project" }).click();
  await expect(owner.getByRole("heading", { level: 1, name: projectName })).toBeVisible();
  const projectId = new URL(owner.url()).pathname.split("/").pop()!;
  await expect(owner.locator("[data-repository]")).toHaveText(repository);
  await owner.getByLabel("User", { exact: true }).fill("reader");
  await owner.getByLabel("Password or token").fill(PASSWORD);
  await owner.getByRole("button", { name: "Save the credential" }).click();
  await expect(owner.locator("[data-credential]")).toContainText("A credential is set");
  await expect(owner.getByLabel("Password or token")).toHaveValue("");
  await owner.screenshot({ path: `${SHOTS}project.png`, fullPage: true });
  const project = await readBack<{ name: string; repository: { host: string; path: string } }>(`/v1/projects/${projectId}`);
  expect(project).toMatchObject({ name: projectName, repository: { host: "forge.example.com", path: `acme/docs-${STAMP}` } });
  console.log(`project read back: ${project.name} at ${project.repository.host}/${project.repository.path}`);

  // The org's own key to a provider.
  await owner.goto("/models");
  const anthropic = owner.getByRole("form", { name: "Key to Anthropic" });
  await anthropic.getByLabel("New key to Anthropic").fill(KEY);
  await anthropic.getByRole("button", { name: "Save the key" }).click();
  await expect(owner.locator("[data-provider='anthropic'] [data-key-line]")).toContainText("A key is set: added by");
  await expect(anthropic.getByLabel("New key to Anthropic")).toHaveValue("");
  await owner.screenshot({ path: `${SHOTS}models.png`, fullPage: true });
  const keys = await readBack<{ provider: string; status: string }[]>("/v1/provider-keys");
  expect(keys.filter((key) => key.provider === "anthropic" && key.status === "live")).toHaveLength(1);
  console.log(`keys read back: ${keys.map((key) => `${key.provider} ${key.status}`).join(", ")}`);

  // An automation that starts a session in the project, off, so it never fires.
  await owner.goto("/automations");
  const form = owner.getByRole("form", { name: "New automation" });
  const automationName = `Nightly tidy ${STAMP}`;
  await form.getByLabel("Name").fill(automationName);
  await form.getByLabel("Session kind").fill("platform_assistant");
  await form.getByLabel("Session title").fill("Tidy the docs");
  await form.getByLabel("Project").selectOption({ label: projectName });
  await form.getByLabel("Brief").fill("Tidy the **docs**.");
  await form.getByLabel("Cost cap a period").fill("2");
  await form.getByLabel("Cost cap a run").fill("0.5");
  await form.getByLabel("State").selectOption("no");
  await form.getByRole("button", { name: "Make the automation" }).click();
  await expect(owner.getByRole("heading", { level: 1, name: automationName })).toBeVisible();
  const automationId = new URL(owner.url()).pathname.split("/").pop()!;
  await owner.screenshot({ path: `${SHOTS}automation.png`, fullPage: true });
  const automation = await readBack<{ name: string; enabled: boolean; trigger: { every: string }; action: { project_id: string } }>(
    `/v1/automations/${automationId}`,
  );
  expect(automation).toMatchObject({ name: automationName, enabled: false, action: { project_id: projectId } });
  console.log(`automation read back: ${automation.name}, every ${automation.trigger.every}, in project ${automation.action.project_id}, enabled ${automation.enabled}`);

  // Neither secret came back, in a reply or on a screen.
  await owner.goto(`/projects/${projectId}`);
  await expect(owner.locator("[data-repository]")).toHaveText(repository);
  for (const secret of [PASSWORD, KEY]) {
    expect(seen.replies.filter((reply) => reply.body.includes(secret)).map((reply) => reply.url)).toEqual([]);
    await expect(owner.locator("body")).not.toContainText(secret);
  }
  console.log(`replies read: ${seen.replies.length}; holding the password or the key: 0`);

  const stranger = await signedIn(browser, `stranger-${STAMP}@example.test`);
  await stranger.goto("/projects");
  await expect(stranger.getByRole("table", { name: "Projects" })).toContainText("No projects yet.");
  await stranger.goto(`/projects/${projectId}`);
  await expect(stranger.getByRole("heading", { level: 1 })).toHaveText("No project here");
  await stranger.goto(`/automations/${automationId}`);
  await expect(stranger.getByRole("heading", { level: 1 })).toHaveText("No automation here");
  await expect(stranger.getByText(projectName)).toHaveCount(0);
  console.log(`another org at /projects/${projectId} and /automations/${automationId}: no project, no automation`);
});
