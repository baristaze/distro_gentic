// Pure: the tenant's knowledge as its screens show it, and an entry's
// request from a person's form. An entry is recalled into a session when
// every word of its trigger appears in what the session is about; an
// agent's suggestion waits for a person's review, and only a kept entry is
// ever recalled. No React, no fetch.
import type { KnowledgeRequest, KnowledgeStatus, KnowledgeView } from "@acme/client";

export const TITLE_MAX = 200;
export const TEXT_MAX = 10_000;
export const TRIGGER_MAX = 20;

export const STATUS_FILTERS: readonly { value: KnowledgeStatus; label: string }[] = [
  { value: "reviewed", label: "Kept" },
  { value: "suggested", label: "Suggested" },
  { value: "rejected", label: "Rejected" },
];

/** A state from the address bar; anything else is the kept entries. */
export function statusFilter(value: string | null): KnowledgeStatus {
  return STATUS_FILTERS.some((filter) => filter.value === value) ? (value as KnowledgeStatus) : "reviewed";
}

export const STATUS_LABEL: Record<KnowledgeStatus, string> = { reviewed: "kept", suggested: "waits for a review", rejected: "rejected" };

export interface EntryRow {
  id: string;
  title: string;
  trigger: string;
  updatedAt: string;
}

export function entryRow(entry: KnowledgeView): EntryRow {
  return { id: entry.id, title: entry.title, trigger: entry.trigger.join(", "), updatedAt: entry.updated_at };
}

export interface EntryDraft {
  title: string;
  trigger: string;
  text: string;
}

export const EMPTY_DRAFT: EntryDraft = { title: "", trigger: "", text: "" };

export function draftOf(entry: KnowledgeView): EntryDraft {
  return { title: entry.title, trigger: entry.trigger.join(", "), text: entry.text };
}

export function entryRequest(draft: EntryDraft): { request: KnowledgeRequest } | { problem: string } {
  const title = draft.title.trim();
  if (!title) return { problem: "Give the entry a title." };
  if (title.length > TITLE_MAX) return { problem: `A title is at most ${TITLE_MAX} characters.` };
  const trigger = [...new Set(draft.trigger.split(",").map((word) => word.trim()).filter(Boolean))];
  if (trigger.length === 0) return { problem: "Name at least one word that recalls it." };
  if (trigger.length > TRIGGER_MAX) return { problem: `An entry is recalled by at most ${TRIGGER_MAX} words.` };
  const text = draft.text.trim();
  if (!text) return { problem: "Write what a session should know." };
  if (text.length > TEXT_MAX) return { problem: `An entry is at most ${TEXT_MAX} characters.` };
  return { request: { title, trigger, text } };
}
