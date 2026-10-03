// Pure: what every record screen says the same way: who did a thing, and a
// cost or a count. No React, no fetch.
import type { UserView } from "@acme/client";

/** A member by name, else by address; one no longer in the org, or not yet
 * read, is said so, never shown as an id. */
export function personName(users: readonly Pick<UserView, "id" | "display_name" | "email">[] | undefined, id: string | null): string {
  if (id === null) return "no one";
  const user = users?.find((each) => each.id === id);
  if (!user) return "a former member";
  return user.display_name.trim() || user.email;
}

/** A cost in millionths of the reference currency, as a figure with two
 * places, or more when a smaller amount would read as nothing. */
export function costLine(micros: number): string {
  const amount = micros / 1_000_000;
  if (micros !== 0 && Math.abs(amount) < 0.01) return amount.toFixed(6).replace(/0+$/, "");
  return amount.toFixed(2);
}

/** A figure a person typed in the reference currency, in millionths; null
 * when it is not a positive amount. */
export function microsOf(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+(\.\d{1,6})?$/.test(trimmed)) return null;
  const [whole, part = ""] = trimmed.split(".");
  const micros = Number(whole) * 1_000_000 + Number(part.padEnd(6, "0"));
  return Number.isSafeInteger(micros) && micros > 0 ? micros : null;
}

/** "1 call", "3 calls": a count and its noun. */
export function countLine(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? one : many}`;
}
