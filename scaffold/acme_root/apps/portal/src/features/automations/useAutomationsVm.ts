import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Role } from "@acme/client";
import { runtimeConfig } from "../../app/config";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useAutomationPrincipal, useAutomations, useCreateAutomation, useGrantPrincipal } from "../../queries/automations";
import { useProjects } from "../../queries/projects";
import { useMe, useUsers } from "../../queries/tenancy";
import { canManageMembers } from "../settings/settingsModel";
import { projectChoice, projectRequired } from "../sessions/sessionsModel";
import { automationRequest, automationRow, EMPTY_DRAFT, principalRoles, type AutomationDraft } from "./automationsModel";

/** The org's automations, a new one, and the automation principal's grant.
 * A member who may write is offered the form; a member who manages the org
 * is offered a grant. */
export function useAutomationsVm() {
  const me = useMe();
  const users = useUsers();
  const list = useAutomations();
  const projects = useProjects();
  const principal = useAutomationPrincipal();
  const create = useCreateAutomation();
  const grant = useGrantPrincipal();
  const navigate = useNavigate();
  const required = projectRequired(runtimeConfig().environment);
  const [draft, setDraft] = useState<AutomationDraft>(EMPTY_DRAFT);
  const [problem, setProblem] = useState<string | null>(null);
  const [role, setRole] = useState<Role | "">("");
  const [grantProblem, setGrantProblem] = useState<string | null>(null);
  const submit = () => {
    const made = automationRequest(draft, { projectRequired: required });
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    create.mutate(made.request, {
      onSuccess: (automation) => navigate(`/automations/${automation.id}`),
      onError: (caught) => setProblem(errorMessage(caught, "The automation was not made.")),
    });
  };
  const submitGrant = () => {
    if (!role) {
      setGrantProblem("Pick a role first.");
      return;
    }
    setGrantProblem(null);
    grant.mutate(role, { onError: (caught) => setGrantProblem(errorMessage(caught, "The role was not granted.")) });
  };
  const held = principal.data;
  return {
    rows: list.data ? list.data.map((each) => automationRow(each, projects.data ?? [])) : null,
    error: list.error,
    mayWrite: me.data?.permissions.includes("write") ?? false,
    mayGrant: canManageMembers(me.data),
    draft,
    setDraft,
    projectOptions: projectChoice(projects.data ?? null, required).options,
    problem,
    submit,
    creating: create.isPending,
    principal: principal.isPending ? undefined : held ? { role: held.role, by: personName(users.data, held.granted_by), at: held.created_at } : null,
    principalError: principal.error,
    roles: principalRoles(me.data?.role),
    role,
    setRole,
    submitGrant,
    granting: grant.isPending,
    grantProblem,
  };
}
