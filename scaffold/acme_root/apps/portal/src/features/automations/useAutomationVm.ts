import { useState } from "react";
import { ApiError } from "@acme/client";
import { runtimeConfig } from "../../app/config";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useAutomation, useUpdateAutomation } from "../../queries/automations";
import { useProjects } from "../../queries/projects";
import { useMe, useUsers } from "../../queries/tenancy";
import { projectChoice, projectRequired } from "../sessions/sessionsModel";
import { actionLine, automationRequest, draftOf, limitsLine, RUNS_AS_LABEL, triggerLine, type AutomationDraft } from "./automationsModel";

/** One automation: what fires it, what it does, its limits, and whose
 * authority it runs on; and the form to edit it, for a member who may
 * write. One that runs as its maker is the maker's alone to edit, which the
 * API holds. An automation the member's org does not hold answers 404. */
export function useAutomationVm(id: string) {
  const me = useMe();
  const users = useUsers();
  const automation = useAutomation(id);
  const projects = useProjects();
  const update = useUpdateAutomation(id);
  const required = projectRequired(runtimeConfig().environment);
  const [draft, setDraft] = useState<AutomationDraft | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const view = automation.data;
  const submit = () => {
    if (!view || !draft) return;
    const made = automationRequest(draft, { kept: view, projectRequired: required });
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
      onError: (caught) => setProblem(errorMessage(caught, "The automation was not saved.")),
    });
  };
  return {
    missing: automation.error instanceof ApiError && automation.error.status === 404,
    error: automation.error,
    automation: view
      ? {
          name: view.name,
          enabled: view.enabled,
          trigger: triggerLine(view.trigger),
          action: actionLine(view.action, projects.data ?? []),
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
    mayWrite: me.data?.permissions.includes("write") ?? false,
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
    projectOptions: projectChoice(projects.data ?? null, required).options,
    problem,
    submit,
    saving: update.isPending,
    saved,
  };
}
