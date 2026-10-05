import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { useCreateProject, useProjects } from "../../queries/projects";
import { useMe } from "../../queries/tenancy";
import { canManageMembers } from "../settings/settingsModel";
import { createRequest, projectRow, type NewProjectDraft } from "./projectsModel";

/** The org's projects, and a new one bound to its repository. Only a member
 * who manages the org sees the form, as only they may make one. */
export function useProjectsVm() {
  const me = useMe();
  const list = useProjects();
  const create = useCreateProject();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<NewProjectDraft>({ name: "", repository: "" });
  const [problem, setProblem] = useState<string | null>(null);
  const submit = () => {
    const made = createRequest(draft);
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    create.mutate(made.request, {
      onSuccess: (project) => navigate(`/settings/projects/${project.id}`),
      onError: (caught) => setProblem(errorMessage(caught, "The project was not made.")),
    });
  };
  return {
    rows: list.data?.map(projectRow) ?? null,
    error: list.error,
    mayManage: canManageMembers(me.data),
    draft,
    setDraft,
    problem,
    submit,
    creating: create.isPending,
  };
}
