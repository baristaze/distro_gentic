// Pure: the models page. The org's own keys as records (who added each,
// when, its state, when it was last used; never a value), the request a key
// typed into its field makes, and for each model role the fill the org chose
// and the fills it may choose. No React, no fetch.
import type { FillChoiceView, FillOptionsView, FillView, ProviderKeyView, ProviderName } from "@acme/client";
import { providerName } from "../providers/outageModel";

export const PROVIDERS: readonly ProviderName[] = ["anthropic", "openai"];
export const KEY_MAX = 4096;

export interface KeyRow {
  id: string;
  provider: string;
  status: ProviderKeyView["status"];
  addedBy: string;
  addedAt: string;
  lastUsedAt: string | null;
}

export function keyRows(keys: readonly ProviderKeyView[], nameOf: (id: string) => string): KeyRow[] {
  return keys.map((key) => ({
    id: key.id,
    provider: providerName(key.provider),
    status: key.status,
    addedBy: nameOf(key.created_by),
    addedAt: key.created_at,
    lastUsedAt: key.last_used_at,
  }));
}

/** What the page says of a provider's key: that the org's live key is set,
 * by whom and when, and when it was last used; or that it holds none. */
export function liveKeyLine(keys: readonly ProviderKeyView[], provider: ProviderName, nameOf: (id: string) => string, when: (iso: string) => string): string {
  const live = keys.find((key) => key.provider === provider && key.status === "live");
  if (!live) {
    const refused = keys.some((key) => key.provider === provider && key.status === "refused");
    return refused ? "The provider refused the org's last key. No key is live." : "No key of the org's own.";
  }
  const used = live.last_used_at ? `last used ${when(live.last_used_at)}` : "not used yet";
  return `A key is set: added by ${nameOf(live.created_by)}, ${when(live.created_at)}; ${used}.`;
}

/** The key a person typed, without the spaces a paste brings around it. */
export function saveKeyRequest(text: string): { value: string } | { problem: string } {
  const value = text.trim();
  if (!value) return { problem: "Paste the key first." };
  if (value.length > KEY_MAX) return { problem: `A key is at most ${KEY_MAX} characters.` };
  return { value };
}

/** A fill in a few words: its provider and model, how hard it works, and its
 * output when that is a schema. */
export function fillLine(fill: FillView): string {
  const parts = [`${providerName(fill.provider)} ${fill.model}`];
  if (fill.effort) parts.push(`${fill.effort} effort`);
  if (fill.output === "schema" && fill.schema_name) parts.push(`answers ${fill.schema_name}`);
  return parts.join(", ");
}

export interface RoleRow {
  role: string;
  chosen: FillView | null;
  options: FillView[];
}

/** Every role the published matrix offers the org or the org chose for, by
 * name. */
export function roleRows(options: readonly FillOptionsView[], choices: readonly FillChoiceView[]): RoleRow[] {
  const roles = new Map<string, RoleRow>();
  for (const option of options) roles.set(option.role, { role: option.role, chosen: null, options: [...option.fills] });
  for (const choice of choices) {
    const row = roles.get(choice.role) ?? { role: choice.role, chosen: null, options: [] };
    row.chosen = choice.fill;
    roles.set(choice.role, row);
  }
  return [...roles.values()].sort((a, b) => a.role.localeCompare(b.role));
}

/** A role's name in words: `code_review` is "code review". */
export function roleLabel(role: string): string {
  return role.replace(/_/g, " ");
}
