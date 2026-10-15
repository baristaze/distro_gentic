import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { common } from "@acme/client";
import { runtimeConfig } from "../../app/config";
import { useSlot } from "../../app/slot";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useAgentAutomationPrincipal, useAgentAutomations, useCreateAgentAutomation, useGrantPrincipal } from "../../queries/agentAutomations";
import { useAgentProjects } from "../../queries/agentProjects";
import { useMe, useUsers } from "../../queries/tenancy";
import { canManageMembers } from "../settings/settingsModel";
import { agentProjectChoice, agentProjectRequired } from "../sessions/sessionsModel";
import { agentAutomationRequest, agentAutomationRow, EMPTY_DRAFT, principalRoles, type AgentAutomationDraft } from "./agentAutomationsModel";

/** The org's agent automations, a new one, and the agent automation principal's grant.
 * A member who may write is offered the form; a member who manages the org
 * is offered a grant. */
export function useAgentAutomationsVm() {
  const me = useMe();
  const users = useUsers();
  const list = useAgentAutomations();
  const agentProjects = useAgentProjects();
  const principal = useAgentAutomationPrincipal();
  const create = useCreateAgentAutomation();
  const grant = useGrantPrincipal();
  const navigate = useNavigate();
  const required = agentProjectRequired(runtimeConfig().environment);
  const firstAgent = useSlot().agents[0]?.kind ?? "";
  // A new agent automation starts the composer's default agent unless another is chosen.
  const [draft, setDraft] = useState<AgentAutomationDraft>(() => ({ ...EMPTY_DRAFT, agentKind: firstAgent }));
  const [problem, setProblem] = useState<string | null>(null);
  const [role, setRole] = useState<common.Role | "">("");
  const [grantProblem, setGrantProblem] = useState<string | null>(null);
  const submit = () => {
    const made = agentAutomationRequest(draft, { agentProjectRequired: required });
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    setProblem(null);
    create.mutate(made.request, {
      onSuccess: (agentAutomation) => navigate(`/agent-automations/${agentAutomation.id}`),
      onError: (caught) => setProblem(errorMessage(caught, "The agent automation was not made.")),
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
    rows: list.data ? list.data.map((each) => agentAutomationRow(each, agentProjects.data ?? [])) : null,
    error: list.error,
    mayWrite: me.data?.permissions.includes("write") ?? false,
    mayGrant: canManageMembers(me.data),
    draft,
    setDraft,
    agentProjectOptions: agentProjectChoice(agentProjects.data ?? null, required).options,
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
