import { useState } from "react";
import { ApiError } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useEditEntry, useEntry, useReviewEntry } from "../../queries/knowledge";
import { useMe, useUsers } from "../../queries/tenancy";
import { draftOf, entryRequest, STATUS_LABEL, type EntryDraft } from "./knowledgeModel";

/** One entry: its text, the words that recall it, and its state; for a
 * member who may write, an edit on the version they read and, while it is a
 * suggestion, a review. An entry the member's org does not hold answers 404. */
export function useEntryVm(id: string) {
  const me = useMe();
  const users = useUsers();
  const entry = useEntry(id);
  const edit = useEditEntry(id);
  const review = useReviewEntry(id);
  const [draft, setDraft] = useState<EntryDraft | null>(null);
  const [version, setVersion] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const view = entry.data;
  const submit = () => {
    if (!draft) return;
    const made = entryRequest(draft);
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    edit.mutate(
      { body: made.request, version },
      { onSuccess: () => setDraft(null), onError: (caught) => setProblem(errorMessage(caught, "The entry was not saved.")) },
    );
  };
  const decide = (keep: boolean) => {
    setProblem(null);
    review.mutate(keep, { onError: (caught) => setProblem(errorMessage(caught, "The review was not saved.")) });
  };
  return {
    missing: entry.error instanceof ApiError && entry.error.status === 404,
    error: entry.error,
    entry: view
      ? {
          title: view.title,
          trigger: view.trigger,
          text: view.text,
          status: view.status,
          state: STATUS_LABEL[view.status],
          /** The session whose agent suggested it; null for a person's own entry. */
          suggestedIn: view.suggested_by,
          reviewedBy: view.reviewed_by ? personName(users.data, view.reviewed_by) : null,
          version: view.version,
          updatedAt: view.updated_at,
        }
      : null,
    mayWrite: me.data?.permissions.includes("write") ?? false,
    draft,
    setDraft,
    startEdit: () => {
      if (!view) return;
      setProblem(null);
      setVersion(view.version);
      setDraft(draftOf(view));
    },
    cancel: () => setDraft(null),
    submit,
    saving: edit.isPending,
    keep: () => decide(true),
    reject: () => decide(false),
    reviewing: review.isPending,
    problem,
  };
}
