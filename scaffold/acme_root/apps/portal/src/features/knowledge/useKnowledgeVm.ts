import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { KnowledgeStatus } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import { useKnowledge, useWriteEntry } from "../../queries/knowledge";
import { useMe } from "../../queries/tenancy";
import { EMPTY_DRAFT, entryRequest, entryRow, statusFilter, type EntryDraft } from "./knowledgeModel";

/** The org's entries in the state the address bar names, and a new entry,
 * kept as it is written, by a member who may write. */
export function useKnowledgeVm() {
  const [params, setParams] = useSearchParams();
  const status = statusFilter(params.get("status"));
  const me = useMe();
  const list = useKnowledge(status);
  const write = useWriteEntry();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<EntryDraft>(EMPTY_DRAFT);
  const [problem, setProblem] = useState<string | null>(null);
  const submit = () => {
    const made = entryRequest(draft);
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    write.mutate(made.request, {
      onSuccess: (entry) => navigate(`/knowledge/${entry.id}`),
      onError: (caught) => setProblem(errorMessage(caught, "The entry was not written.")),
    });
  };
  return {
    status,
    setStatus: (next: KnowledgeStatus) => setParams(next === "reviewed" ? {} : { status: next }),
    rows: list.data?.map(entryRow) ?? null,
    error: list.error,
    mayWrite: me.data?.permissions.includes("write") ?? false,
    draft,
    setDraft,
    problem,
    submit,
    writing: write.isPending,
  };
}
