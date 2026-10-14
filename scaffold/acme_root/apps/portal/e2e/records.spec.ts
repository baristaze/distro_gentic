// The record screens over a running local stack; only the API and this dev
// server need to be up. In Settings, the seeded owner makes an agent project and
// gives its repository a read credential, saves the org's own key to a
// provider (the stack's probe twin takes it, so no provider is called), and
// creates an API key; then makes an agent automation that starts a session in the
// agent project. Each record is then read back from the API as the owner. The
// credential's password and the provider key go out once, in their writes:
// no reply the portal reads holds either, and no screen shows either. The
// API key's secret comes back once, in its create's reply, and shows until
// "Done": no other reply holds it, and no screen shows it after. A person of
// another org then finds none of the records.
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
  const replies: { url: string; method: string; body: string }[] = [];
  let bearer = "";
  page.on("request", (request) => {
    const auth = request.headers()["authorization"];
    if (auth && request.url().includes("/v1/")) bearer = auth;
  });
  page.on("response", async (response) => {
    if (!response.url().includes("/v1/")) return;
    replies.push({ url: response.url(), method: response.request().method(), body: await response.text().catch(() => "") });
  });
  return { replies, bearer: () => bearer };
}

test("an owner keeps an agent project, a key, an API key, and an agent automation through the screens; the secrets show nowhere after they are saved, and another org sees none of it", async ({ browser }) => {
  const owner = await signedIn(browser, OWNER, ORG);
  const seen = listen(owner);
  const readBack = async <T>(path: string): Promise<T> => {
    const response = await owner.request.get(path, { headers: { authorization: seen.bearer() } });
    expect(response.status()).toBe(200);
    const body = await response.text();
    seen.replies.push({ url: path, method: "GET", body });
    return JSON.parse(body) as T;
  };

  // In Settings, an agent project bound to its repository, and the repository's read credential.
  await owner.goto("/settings/agent-projects");
  const agentProjectName = `Docs ${STAMP}`;
  const repository = `forge.example.com/acme/docs-${STAMP}`;
  await owner.getByLabel("Name").fill(agentProjectName);
  await owner.getByLabel("Repository").fill(`https://${repository}.git`);
  await owner.getByRole("button", { name: "Make the agent project" }).click();
  await expect(owner.getByRole("heading", { level: 1, name: agentProjectName })).toBeVisible();
  const agentProjectId = new URL(owner.url()).pathname.split("/").pop()!;
  await expect(owner.locator("[data-repository]")).toHaveText(repository);
  await owner.getByLabel("User", { exact: true }).fill("reader");
  await owner.getByLabel("Password or token").fill(PASSWORD);
  await owner.getByRole("button", { name: "Save the credential" }).click();
  await expect(owner.locator("[data-credential]")).toContainText("A credential is set");
  await expect(owner.getByLabel("Password or token")).toHaveValue("");
  await owner.screenshot({ path: `${SHOTS}agent_project.png`, fullPage: true });
  const agentProject = await readBack<{ name: string; repository: { host: string; path: string } }>(`/v1/agent-projects/${agentProjectId}`);
  expect(agentProject).toMatchObject({ name: agentProjectName, repository: { host: "forge.example.com", path: `acme/docs-${STAMP}` } });
  console.log(`agentProject read back: ${agentProject.name} at ${agentProject.repository.host}/${agentProject.repository.path}`);

  // The org's own key to a provider.
  await owner.goto("/settings/models");
  const anthropic = owner.getByRole("form", { name: "Key to Anthropic" });
  await anthropic.getByLabel("New key to Anthropic").fill(KEY);
  await anthropic.getByRole("button", { name: "Save the key" }).click();
  await expect(owner.locator("[data-provider='anthropic'] [data-key-line]")).toContainText("A key is set: added by");
  await expect(anthropic.getByLabel("New key to Anthropic")).toHaveValue("");
  await owner.screenshot({ path: `${SHOTS}models.png`, fullPage: true });
  const keys = await readBack<{ provider: string; status: string }[]>("/v1/provider-keys");
  expect(keys.filter((key) => key.provider === "anthropic" && key.status === "live")).toHaveLength(1);
  console.log(`keys read back: ${keys.map((key) => `${key.provider} ${key.status}`).join(", ")}`);

  // An API key a program calls with: its secret shows once, until Done.
  await owner.goto("/settings/api-keys");
  const apiKeyName = `ci-${STAMP}`;
  await owner.getByLabel("New key name").fill(apiKeyName);
  await owner.getByRole("button", { name: "Create key" }).click();
  const issued = owner.locator("[data-issued-key]");
  await expect(issued).toBeVisible();
  const apiKey = (await issued.textContent()) ?? "";
  expect(apiKey.length).toBeGreaterThan(16);
  await owner.getByRole("button", { name: "Done" }).click();
  await expect(issued).toHaveCount(0);
  await expect(owner.locator("body")).toContainText(apiKeyName);
  await expect(owner.getByLabel("New key name")).toHaveValue("");
  await owner.screenshot({ path: `${SHOTS}api-keys.png`, fullPage: true });
  const apiKeys = await readBack<{ items: { name: string }[] }>("/v1/api-keys?limit=50");
  expect(apiKeys.items.filter((key) => key.name === apiKeyName)).toHaveLength(1);
  console.log(`API key read back: ${apiKeyName}; shown once, then gone from the screen`);

  // An agent automation that starts a session in the agent project, off, so it never fires.
  await owner.goto("/agent-automations");
  const form = owner.getByRole("form", { name: "New agent automation" });
  const agentAutomationName = `Nightly tidy ${STAMP}`;
  await form.getByLabel("Name").fill(agentAutomationName);
  await form.getByLabel("Agent", { exact: true }).selectOption("platform_assistant");
  await form.getByLabel("Session title").fill("Tidy the docs");
  await form.getByLabel("Agent project").selectOption({ label: agentProjectName });
  await form.getByLabel("Brief").fill("Tidy the **docs**.");
  await form.getByLabel("Cost cap a period").fill("2");
  await form.getByLabel("Cost cap a run", { exact: true }).fill("0.5");
  await form.getByLabel("State").selectOption("no");
  await form.getByRole("button", { name: "Make the agent automation" }).click();
  await expect(owner.getByRole("heading", { level: 1, name: agentAutomationName })).toBeVisible();
  const agentAutomationId = new URL(owner.url()).pathname.split("/").pop()!;
  await owner.screenshot({ path: `${SHOTS}agentAutomation.png`, fullPage: true });
  const agentAutomation = await readBack<{ name: string; enabled: boolean; trigger: { every: string }; action: { agent_project_id: string } }>(
    `/v1/agent-automations/${agentAutomationId}`,
  );
  expect(agentAutomation).toMatchObject({ name: agentAutomationName, enabled: false, action: { agent_project_id: agentProjectId } });
  console.log(`agentAutomation read back: ${agentAutomation.name}, every ${agentAutomation.trigger.every}, in agent project ${agentAutomation.action.agent_project_id}, enabled ${agentAutomation.enabled}`);

  // No secret came back after its write, in a reply or on a screen. The API
  // key's own create is the one reply that holds it.
  const created = (reply: { url: string; method: string }) => reply.method === "POST" && new URL(reply.url, "http://x").pathname === "/v1/api-keys";
  for (const address of [`/settings/agent-projects/${agentProjectId}`, "/settings/models", "/settings/api-keys", `/agent-automations/${agentAutomationId}`]) {
    await owner.goto(address);
    await expect(owner.getByRole("heading", { level: 1 })).toBeVisible();
    for (const secret of [PASSWORD, KEY, apiKey]) await expect(owner.locator("body")).not.toContainText(secret);
  }
  for (const secret of [PASSWORD, KEY, apiKey]) {
    expect(seen.replies.filter((reply) => reply.body.includes(secret) && !created(reply)).map((reply) => reply.url)).toEqual([]);
  }
  console.log(`replies read: ${seen.replies.length}; holding the password, the provider key, or the API key past its create: 0`);

  const stranger = await signedIn(browser, `stranger-${STAMP}@example.test`);
  await stranger.goto("/settings/agent-projects");
  await expect(stranger.getByRole("table", { name: "Agent projects" })).toContainText("No agent projects yet.");
  await stranger.goto(`/settings/agent-projects/${agentProjectId}`);
  await expect(stranger.getByRole("heading", { level: 1 })).toHaveText("No agent project here");
  await stranger.goto(`/agent-automations/${agentAutomationId}`);
  await expect(stranger.getByRole("heading", { level: 1 })).toHaveText("No agent automation here");
  await expect(stranger.getByText(agentProjectName)).toHaveCount(0);
  console.log(`another org at /agent-projects/${agentProjectId} and /agent-automations/${agentAutomationId}: no agent project, no agent automation`);
});
