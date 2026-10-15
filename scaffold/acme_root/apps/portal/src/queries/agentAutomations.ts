// The tenant's agent automations, made and edited by a person, and the tenant's
// agent automation principal: its grant read, and a role granted to it. The list
// is read whole, a page at a time, each page after the last id.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type agent_automations, type common } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

const PAGE_SIZE = 200;
const path = (id: string) => `/v1/agent-automations/${encodeURIComponent(id)}`;

export function useAgentAutomations() {
  return useQuery({
    queryKey: keys.agentAutomations.list(PAGE_SIZE),
    queryFn: async ({ signal }) => {
      const read: agent_automations.AgentAutomationView[] = [];
      for (let after: string | null = null; ; ) {
        const cursor: string = after ? `&after=${encodeURIComponent(after)}` : "";
        const page = await api.get<agent_automations.AgentAutomationView[]>(`/v1/agent-automations?limit=${PAGE_SIZE}${cursor}`, { signal });
        read.push(...page);
        const last = page[page.length - 1];
        if (page.length < PAGE_SIZE || last === undefined) return read;
        after = last.id;
      }
    },
  });
}

export function useAgentAutomation(id: string) {
  return useQuery({
    queryKey: keys.agentAutomations.one(id),
    queryFn: ({ signal }) => api.get<agent_automations.AgentAutomationView>(path(id), { signal }),
  });
}

export function useCreateAgentAutomation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: agent_automations.AgentAutomationRequest) => api.post<agent_automations.AgentAutomationView>("/v1/agent-automations", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.agentAutomations.list(PAGE_SIZE) }),
  });
}

export function useUpdateAgentAutomation(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: agent_automations.AgentAutomationRequest) => api.request<agent_automations.AgentAutomationView>("PUT", path(id), body),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.agentAutomations.one(id), saved);
      return queryClient.invalidateQueries({ queryKey: keys.agentAutomations.list(PAGE_SIZE) });
    },
  });
}

/** The principal's grant, or null while the tenant has granted it none. */
export function useAgentAutomationPrincipal() {
  return useQuery({
    queryKey: keys.agentAutomations.principal,
    queryFn: async ({ signal }) => {
      try {
        return await api.get<agent_automations.AgentAutomationPrincipalView>("/v1/agent-automations/principal", { signal });
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) return null;
        throw caught;
      }
    },
  });
}

export function useGrantPrincipal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (role: common.Role) => api.request<agent_automations.AgentAutomationPrincipalView>("PUT", "/v1/agent-automations/principal", { role }),
    onSuccess: (granted) => queryClient.setQueryData(keys.agentAutomations.principal, granted),
  });
}
