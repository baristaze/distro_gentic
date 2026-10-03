import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { runtimeConfig } from "../../app/config";
import { errorMessage } from "../../app/errorMessage";
import { useAgentSessions, useStartSession } from "../../queries/agentSessions";
import { useProjects } from "../../queries/projects";
import { useMe } from "../../queries/tenancy";
import {
  projectChoice,
  projectRequired,
  sessionRow,
  startRequest,
  statusFilter,
  type NewSessionDraft,
  type StatusFilter,
} from "./sessionsModel";

/** The tenant's sessions in the status the address bar names, a page at a
 * time, and a new one started from a title, a kind, and the project it works
 * in. A member who may not write sees the list and no form. */
export function useSessionsVm() {
  const [params, setParams] = useSearchParams();
  const filter = statusFilter(params.get("status"));
  const list = useAgentSessions(filter === "any" ? null : filter);
  const me = useMe();
  const mayWrite = me.data?.permissions.includes("write") ?? false;
  const projects = useProjects(mayWrite);
  const required = projectRequired(runtimeConfig().environment);
  const choice = projectChoice(projects.data ?? null, required);
  const start = useStartSession();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<NewSessionDraft>({ title: "", kind: "", projectId: "" });
  const [problem, setProblem] = useState<string | null>(null);
  const submit = () => {
    const made = startRequest(draft, { required, count: projects.data?.length ?? 0 });
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
    mayWrite,
    draft,
    setDraft,
    projectOptions: choice.options,
    // What the form says: the last start's problem, or why none can start.
    problem: problem ?? (projects.error ? errorMessage(projects.error, "The projects could not be read.") : choice.problem),
    submit,
    starting: start.isPending,
  };
}
