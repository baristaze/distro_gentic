// @vitest-environment jsdom
// The models page over a fake transport that answers as the API does: each
// org reads its own keys' records, which never carry a value, and its own
// choices. A key typed into its field goes out once, in the save, and the
// page never shows it again. A member who does not manage the org is
// offered no field and no choice.
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { FillView, ProviderKeyView } from "@acme/client";
import { buttons, container, enter, field, mount, newNet, notFound, PEOPLE, press, unmount, writes, type Call } from "../screenTesting";
import { ModelsPage } from "./ModelsPage";

const net = vi.hoisted(() => ({}) as ReturnType<typeof newNet>);
vi.mock("../../app/api", async () => (await import("../screenTesting")).fakeApi(net));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const SECRET = "sk-test-never-on-a-screen-5678";
const fill = (model: string): FillView => ({
  provider: "anthropic",
  model,
  effort: null,
  thinking_budget: null,
  max_output_tokens: 4096,
  output: "text",
  schema_name: null,
  context_window: 200_000,
  eligibility: { region: null, zero_retention: false },
});
const key = (org: "a" | "b", provider: ProviderKeyView["provider"]): ProviderKeyView => ({
  id: `k${org}`,
  provider,
  status: "live",
  created_at: "2026-10-01T09:00:00Z",
  created_by: PEOPLE[org].id,
  last_used_at: null,
});
const KEYS = { a: [key("a", "anthropic")], b: [key("b", "openai")] };
const OPTIONS = { a: [{ role: "worker", fills: [fill("model-a1"), fill("model-a2")] }], b: [{ role: "judge", fills: [fill("model-b1")] }] };

function answer(call: Call): unknown {
  if (call.method === "GET" && call.path.startsWith("/v1/provider-keys?")) return KEYS[net.org];
  if (call.method === "GET" && call.path === "/v1/matrix/options") return OPTIONS[net.org];
  if (call.method === "GET" && call.path === "/v1/matrix/choices") return [];
  if (call.method === "PUT" && call.path.startsWith("/v1/provider-keys/")) return { ...key(net.org, "openai"), id: "knew" };
  if (call.method === "PUT" && call.path.startsWith("/v1/matrix/choices/")) {
    return { id: "c1", role: "worker", fill: (call.body as { fill: FillView }).fill, created_at: "", updated_at: "", updated_by: PEOPLE[net.org].id };
  }
  return notFound(call.path);
}

const routes = [{ path: "/models", Component: ModelsPage }];

beforeEach(() => Object.assign(net, newNet(), { answer }));
afterEach(unmount);

it("shows the org's own key records and options, none of another's", async () => {
  await mount(routes, "/models");
  const line = (provider: string) => container.querySelector(`[data-provider='${provider}'] [data-key-line]`)!.textContent;
  expect(line("anthropic")).toMatch(/^A key is set: added by Ada, .+; not used yet\.$/);
  expect(line("openai")).toBe("No key of the org's own.");
  expect(container.textContent).toContain("model-a1");
  expect(container.textContent).not.toContain("model-b1");
  expect(container.textContent).not.toContain("Bea");
});

it("sends a key once and never shows it back", async () => {
  await mount(routes, "/models");
  await enter("New key to OpenAI", ` ${SECRET} `);
  expect(field("New key to OpenAI")!.getAttribute("type")).toBe("password");
  const save = container.querySelector("form[aria-label='Key to OpenAI']")!;
  await press("Save the key", save);
  expect(writes(net)).toEqual([{ method: "PUT", path: "/v1/provider-keys/openai", body: { value: SECRET } }]);
  expect(field("New key to OpenAI")!.value).toBe("");
  expect(container.innerHTML).not.toContain(SECRET);
  expect(net.calls.filter((call) => call.method === "GET" && call.path.startsWith("/v1/provider-keys?")).length).toBeGreaterThan(1);
});

it("chooses a role's model among its options", async () => {
  await mount(routes, "/models");
  await enter("Model for worker", "1");
  await press("Choose");
  expect(writes(net)).toEqual([{ method: "PUT", path: "/v1/matrix/choices/worker", body: { fill: fill("model-a2") } }]);
});

it("offers a member who does not manage the org no key field and no choice", async () => {
  net.role = "member";
  await mount(routes, "/models");
  expect(container.querySelectorAll("form")).toHaveLength(0);
  expect(field("Model for worker")).toBeUndefined();
  expect(buttons()).not.toContain("Choose");
  expect(container.querySelector("table[aria-label='Roles']")!.textContent).toContain("worker");
});
