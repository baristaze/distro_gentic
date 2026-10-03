import { describe, expect, it } from "vitest";
import type { FillView, ProviderKeyView } from "@acme/client";
import { fillLine, keyRows, liveKeyLine, roleRows, saveKeyRequest } from "./modelsModel";

const key = (id: string, provider: ProviderKeyView["provider"], status: ProviderKeyView["status"], last_used_at: string | null = null): ProviderKeyView => ({
  id,
  provider,
  status,
  created_at: "2026-10-01T09:00:00Z",
  created_by: "u1",
  last_used_at,
});
const fill = (model: string, fields: Partial<FillView> = {}): FillView => ({
  provider: "anthropic",
  model,
  effort: null,
  thinking_budget: null,
  max_output_tokens: 4096,
  output: "text",
  schema_name: null,
  context_window: 200_000,
  eligibility: { region: null, zero_retention: false },
  ...fields,
});
const nameOf = (id: string) => (id === "u1" ? "Ada" : "a former member");
const when = (iso: string) => iso.slice(0, 10);

describe("liveKeyLine", () => {
  it("says who set the live key and when, and when it was last used", () => {
    const keys = [key("k2", "anthropic", "live", "2026-10-02T09:00:00Z"), key("k1", "anthropic", "rotated")];
    expect(liveKeyLine(keys, "anthropic", nameOf, when)).toBe("A key is set: added by Ada, 2026-10-01; last used 2026-10-02.");
    expect(liveKeyLine([key("k3", "openai", "live")], "openai", nameOf, when)).toBe("A key is set: added by Ada, 2026-10-01; not used yet.");
  });
  it("says when none is live", () => {
    expect(liveKeyLine([], "openai", nameOf, when)).toBe("No key of the org's own.");
    expect(liveKeyLine([key("k1", "openai", "refused")], "openai", nameOf, when)).toBe("The provider refused the org's last key. No key is live.");
  });
});

it("lists every key record by its state, never a value", () => {
  const rows = keyRows([key("k1", "openai", "rotated")], nameOf);
  expect(rows).toEqual([{ id: "k1", provider: "OpenAI", status: "rotated", addedBy: "Ada", addedAt: "2026-10-01T09:00:00Z", lastUsedAt: null }]);
  expect(JSON.stringify(rows)).not.toContain("value");
});

describe("saveKeyRequest", () => {
  it("drops the spaces a paste brings", () => {
    expect(saveKeyRequest("  sk-test-1 \n")).toEqual({ value: "sk-test-1" });
  });
  it("refuses an empty or an oversized key", () => {
    expect(saveKeyRequest(" ")).toEqual({ problem: "Paste the key first." });
    expect(saveKeyRequest("x".repeat(4097))).toEqual({ problem: "A key is at most 4096 characters." });
  });
});

it("says a fill in a few words", () => {
  expect(fillLine(fill("claude-x"))).toBe("Anthropic claude-x");
  expect(fillLine(fill("claude-x", { effort: "high", output: "schema", schema_name: "verdict" }))).toBe("Anthropic claude-x, high effort, answers verdict");
});

it("joins each role's options and the org's choice, by role", () => {
  const rows = roleRows(
    [
      { role: "worker", fills: [fill("a"), fill("b")] },
      { role: "judge", fills: [] },
    ],
    [{ id: "c1", role: "worker", fill: fill("b"), created_at: "", updated_at: "", updated_by: "u1" }],
  );
  expect(rows.map((row) => [row.role, row.chosen?.model ?? null, row.options.length])).toEqual([
    ["judge", null, 0],
    ["worker", "b", 2],
  ]);
});
