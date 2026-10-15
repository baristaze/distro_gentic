// The tenant's agent projects: what a new session may start in, each bound to its
// repository. The list is read whole, a page at a time, each page after the
// last id the one before held. The fetch credential is written and never
// read back: its write answers who gave it and when, never its value.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { agent_projects } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The largest page the server gives. */
const PAGE_SIZE = 200;

const path = (id: string) => `/v1/agent-projects/${encodeURIComponent(id)}`;

export function useAgentProjects(enabled = true) {
  return useQuery({
    queryKey: keys.agentProjects.list(PAGE_SIZE),
    queryFn: async ({ signal }) => {
      const read: agent_projects.AgentProjectView[] = [];
      for (let after: string | null = null; ; ) {
        const cursor: string = after ? `&after=${encodeURIComponent(after)}` : "";
        const page = await api.get<agent_projects.AgentProjectView[]>(`/v1/agent-projects?limit=${PAGE_SIZE}${cursor}`, { signal });
        read.push(...page);
        const last = page[page.length - 1];
        if (page.length < PAGE_SIZE || last === undefined) return read;
        after = last.id;
      }
    },
    enabled,
  });
}

export function useAgentProject(id: string) {
  return useQuery({
    queryKey: keys.agentProjects.one(id),
    queryFn: ({ signal }) => api.get<agent_projects.AgentProjectView>(path(id), { signal }),
  });
}

export function useCreateAgentProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: agent_projects.CreateAgentProjectRequest) => api.post<agent_projects.AgentProjectView>("/v1/agent-projects", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.agentProjects.all }),
  });
}

export function useRenameAgentProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.patch<agent_projects.AgentProjectView>(path(id), { name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.agentProjects.all }),
  });
}

export function useRemoveAgentProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<agent_projects.AgentProjectView>(path(id)),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: keys.agentProjects.one(id) });
      return queryClient.invalidateQueries({ queryKey: keys.agentProjects.list(PAGE_SIZE) });
    },
  });
}

/** The repository's read credential; a later one replaces it. */
export function usePutCredential(id: string) {
  return useMutation({
    mutationFn: (body: agent_projects.FetchCredentialRequest) => api.request<agent_projects.FetchCredentialView>("PUT", `${path(id)}/credential`, body),
  });
}
