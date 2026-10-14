import { useState } from "react";
import { ApiError } from "@acme/client";
import { runtimeConfig } from "../../app/config";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useAgentAutomation, useUpdateAgentAutomation } from "../../queries/agentAutomations";
import { useAgentProjects } from "../../queries/agentProjects";
import { useMe, useUsers } from "../../queries/tenancy";
import { agentProjectChoice, agentProjectRequired } from "../sessions/sessionsModel";
import { actionLine, agentAutomationRequest, draftOf, limitsLine, platformAction, RUNS_AS_LABEL, triggerLine, type AgentAutomationDraft } from "./agentAutomationsModel";

/** One agent automation: what fires it, what it does, its limits, and whose
 * authority it runs on; and the form to edit it, for a member who may
 * write. One that runs as its maker is the maker's alone to edit, which the
 * API holds. An agent automation the member's org does not hold answers 404. */
export function useAgentAutomationVm(id: string) {
  const me = useMe();
  const users = useUsers();
  const agentAutomation = useAgentAutomation(id);
  const agentProjects = useAgentProjects();
  const update = useUpdateAgentAutomation(id);
  const required = agentProjectRequired(runtimeConfig().environment);
  const [draft, setDraft] = useState<AgentAutomationDraft | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const view = agentAutomation.data;
  const submit = () => {
    if (!view || !draft) return;
    const made = agentAutomationRequest(draft, { kept: view, agentProjectRequired: required });
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    update.mutate(made.request, {
      onSuccess: () => {
        setDraft(null);
        setSaved(true);
      },
      onError: (caught) => setProblem(errorMessage(caught, "The agent automation was not saved.")),
    });
  };
  return {
    missing: agentAutomation.error instanceof ApiError && agentAutomation.error.status === 404,
    error: agentAutomation.error,
    agentAutomation: view
      ? {
          name: view.name,
          enabled: view.enabled,
          trigger: triggerLine(view.trigger),
          action: actionLine(view.action, agentProjects.data ?? []),
          brief: view.action.brief,
          limits: limitsLine(view.limits),
          runsAs: RUNS_AS_LABEL[view.runs_as],
          ownEvents: view.own_events,
          createdBy: personName(users.data, view.created_by),
          createdAt: view.created_at,
          updatedBy: personName(users.data, view.updated_by),
          updatedAt: view.updated_at,
        }
      : null,
    // A product's own action is its product's to write, never this form's.
    mayWrite: (me.data?.permissions.includes("write") ?? false) && (view ? platformAction(view.action.kind) : false),
    editing: draft !== null,
    edit: () => {
      if (!view) return;
      setSaved(false);
      setProblem(null);
      setDraft(draftOf(view));
    },
    cancel: () => setDraft(null),
    draft,
    setDraft,
    agentProjectOptions: agentProjectChoice(agentProjects.data ?? null, required).options,
    problem,
    submit,
    saving: update.isPending,
    saved,
  };
}
