// The tenant's automations, made and edited by a person, and the tenant's
// automation principal: its grant read, and a role granted to it. The list
// is read whole, a page at a time, each page after the last id.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type AutomationPrincipalView, type AutomationRequest, type AutomationView, type Role } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

const PAGE_SIZE = 200;
const path = (id: string) => `/v1/automations/${encodeURIComponent(id)}`;

export function useAutomations() {
  return useQuery({
    queryKey: keys.automations.list(PAGE_SIZE),
    queryFn: async ({ signal }) => {
      const read: AutomationView[] = [];
      for (let after: string | null = null; ; ) {
        const cursor: string = after ? `&after=${encodeURIComponent(after)}` : "";
        const page = await api.get<AutomationView[]>(`/v1/automations?limit=${PAGE_SIZE}${cursor}`, { signal });
        read.push(...page);
        const last = page[page.length - 1];
        if (page.length < PAGE_SIZE || last === undefined) return read;
        after = last.id;
      }
    },
  });
}

export function useAutomation(id: string) {
  return useQuery({
    queryKey: keys.automations.one(id),
    queryFn: ({ signal }) => api.get<AutomationView>(path(id), { signal }),
  });
}

export function useCreateAutomation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AutomationRequest) => api.post<AutomationView>("/v1/automations", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.automations.list(PAGE_SIZE) }),
  });
}

export function useUpdateAutomation(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AutomationRequest) => api.request<AutomationView>("PUT", path(id), body),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.automations.one(id), saved);
      return queryClient.invalidateQueries({ queryKey: keys.automations.list(PAGE_SIZE) });
    },
  });
}

/** The principal's grant, or null while the tenant has granted it none. */
export function useAutomationPrincipal() {
  return useQuery({
    queryKey: keys.automations.principal,
    queryFn: async ({ signal }) => {
      try {
        return await api.get<AutomationPrincipalView>("/v1/automations/principal", { signal });
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
    mutationFn: (role: Role) => api.request<AutomationPrincipalView>("PUT", "/v1/automations/principal", { role }),
    onSuccess: (granted) => queryClient.setQueryData(keys.automations.principal, granted),
  });
}
