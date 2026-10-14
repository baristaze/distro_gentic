import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { useCreateAgentProject, useAgentProjects } from "../../queries/agentProjects";
import { useMe } from "../../queries/tenancy";
import { canManageMembers } from "../settings/settingsModel";
import { createRequest, agentProjectRow, type NewAgentProjectDraft } from "./agentProjectsModel";

/** The org's agent projects, and a new one bound to its repository. Only a member
 * who manages the org sees the form, as only they may make one. */
export function useAgentProjectsVm() {
  const me = useMe();
  const list = useAgentProjects();
  const create = useCreateAgentProject();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<NewAgentProjectDraft>({ name: "", repository: "" });
  const [problem, setProblem] = useState<string | null>(null);
  const submit = () => {
    const made = createRequest(draft);
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    create.mutate(made.request, {
      onSuccess: (agentProject) => navigate(`/settings/agent-projects/${agentProject.id}`),
      onError: (caught) => setProblem(errorMessage(caught, "The agent project was not made.")),
    });
  };
  return {
    rows: list.data?.map(agentProjectRow) ?? null,
    error: list.error,
    mayManage: canManageMembers(me.data),
    draft,
    setDraft,
    problem,
    submit,
    creating: create.isPending,
  };
}
