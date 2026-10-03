import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { useAgentSessions, useStartSession } from "../../queries/agentSessions";
import { useMe } from "../../queries/tenancy";
import { sessionRow, startRequest, statusFilter, type NewSessionDraft, type StatusFilter } from "./sessionsModel";

/** The tenant's sessions in the status the address bar names, a page at a
 * time, and a new one started from a title and a kind. A member who may not
 * write sees the list and no form. */
export function useSessionsVm() {
  const [params, setParams] = useSearchParams();
  const filter = statusFilter(params.get("status"));
  const list = useAgentSessions(filter === "any" ? null : filter);
  const me = useMe();
  const start = useStartSession();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<NewSessionDraft>({ title: "", kind: "" });
  const [problem, setProblem] = useState<string | null>(null);
  const submit = () => {
    const made = startRequest(draft);
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    start.mutate(made.request, {
      onSuccess: (session) => navigate(`/sessions/${session.id}`),
      onError: (caught) => setProblem(errorMessage(caught, "The session did not start.")),
    });
  };
  return {
    filter,
    setFilter: (next: StatusFilter) => setParams(next === "any" ? {} : { status: next }),
    rows: list.data?.map(sessionRow) ?? null,
    error: list.error,
    hasMore: list.hasNextPage,
    loadingMore: list.isFetchingNextPage,
    loadMore: () => void list.fetchNextPage(),
    mayWrite: me.data?.permissions.includes("write") ?? false,
    draft,
    setDraft,
    problem,
    submit,
    starting: start.isPending,
  };
}
