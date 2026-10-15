import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, type agent_projects } from "@acme/client";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useAgentProject, usePutCredential, useRemoveAgentProject, useRenameAgentProject } from "../../queries/agentProjects";
import { useMe, useUsers } from "../../queries/tenancy";
import { canManageMembers } from "../settings/settingsModel";
import { credentialRequest, renameRequest, repositoryLine, type CredentialDraft } from "./agentProjectsModel";

/** One agent project: its repository, who made it, a new name, the fetch
 * credential, and its removal. The credential's password lives in the form
 * until it is sent, and is cleared from it when the write lands; the page
 * then shows only who set it and when. An agent project the member's org does not
 * hold answers 404, and the page shows nothing of it. */
export function useAgentProjectVm(id: string) {
  const me = useMe();
  const users = useUsers();
  const agentProject = useAgentProject(id);
  const rename = useRenameAgentProject(id);
  const remove = useRemoveAgentProject(id);
  const credential = usePutCredential(id);
  const navigate = useNavigate();
  const [name, setName] = useState<string | null>(null);
  const [renameProblem, setRenameProblem] = useState<string | null>(null);
  const [draft, setDraft] = useState<CredentialDraft>({ username: "", password: "" });
  const [credentialProblem, setCredentialProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState<agent_projects.FetchCredentialView | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [removeProblem, setRemoveProblem] = useState<string | null>(null);
  const current = agentProject.data?.name ?? "";
  const submitRename = () => {
    const made = renameRequest(name ?? current, current);
    if (made === null) return;
    if ("problem" in made) {
      setRenameProblem(made.problem);
      return;
    }
    setRenameProblem(null);
    rename.mutate(made.name, {
      onSuccess: () => setName(null),
      onError: (caught) => setRenameProblem(errorMessage(caught, "The agent project was not renamed.")),
    });
  };
  const submitCredential = () => {
    const made = credentialRequest(draft);
    if ("problem" in made) {
      setCredentialProblem(made.problem);
      return;
    }
    setCredentialProblem(null);
    credential.mutate(made.request, {
      onSuccess: (view) => {
        setSaved(view);
        setDraft({ username: "", password: "" });
      },
      onError: (caught) => setCredentialProblem(errorMessage(caught, "The credential was not saved.")),
    });
  };
  const confirmRemove = () =>
    remove.mutate(undefined, {
      onSuccess: () => navigate("/settings/agent-projects"),
      onError: (caught) => {
        setConfirming(false);
        setRemoveProblem(errorMessage(caught, "The agent project was not removed."));
      },
    });
  const view = agentProject.data;
  return {
    missing: agentProject.error instanceof ApiError && agentProject.error.status === 404,
    error: agentProject.error,
    agentProject: view
      ? {
          name: view.name,
          repository: repositoryLine(view.repository),
          createdBy: personName(users.data, view.created_by),
          createdAt: view.created_at,
          updatedBy: personName(users.data, view.updated_by),
          updatedAt: view.updated_at,
        }
      : null,
    mayManage: canManageMembers(me.data),
    name: name ?? current,
    setName,
    renameProblem,
    submitRename,
    renaming: rename.isPending,
    draft,
    setDraft,
    credentialProblem,
    submitCredential,
    savingCredential: credential.isPending,
    saved: saved ? { at: saved.updated_at, by: personName(users.data, saved.updated_by) } : null,
    confirming,
    askRemove: () => {
      setRemoveProblem(null);
      setConfirming(true);
    },
    cancelRemove: () => setConfirming(false),
    confirmRemove,
    removing: remove.isPending,
    removeProblem,
  };
}
