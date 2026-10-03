// The tenant's projects: what a new session may start in, each bound to its
// repository. The list is read whole, a page at a time, each page after the
// last id the one before held. The fetch credential is written and never
// read back: its write answers who gave it and when, never its value.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { CreateProjectRequest, FetchCredentialRequest, FetchCredentialView, ProjectView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The largest page the server gives. */
const PAGE_SIZE = 200;

const path = (id: string) => `/v1/projects/${encodeURIComponent(id)}`;

export function useProjects(enabled = true) {
  return useQuery({
    queryKey: keys.projects.list(PAGE_SIZE),
    queryFn: async ({ signal }) => {
      const read: ProjectView[] = [];
      for (let after: string | null = null; ; ) {
        const cursor: string = after ? `&after=${encodeURIComponent(after)}` : "";
        const page = await api.get<ProjectView[]>(`/v1/projects?limit=${PAGE_SIZE}${cursor}`, { signal });
        read.push(...page);
        const last = page[page.length - 1];
        if (page.length < PAGE_SIZE || last === undefined) return read;
        after = last.id;
      }
    },
    enabled,
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: keys.projects.one(id),
    queryFn: ({ signal }) => api.get<ProjectView>(path(id), { signal }),
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateProjectRequest) => api.post<ProjectView>("/v1/projects", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.projects.all }),
  });
}

export function useRenameProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.patch<ProjectView>(path(id), { name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.projects.all }),
  });
}

export function useRemoveProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<ProjectView>(path(id)),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: keys.projects.one(id) });
      return queryClient.invalidateQueries({ queryKey: keys.projects.list(PAGE_SIZE) });
    },
  });
}

/** The repository's read credential; a later one replaces it. */
export function usePutCredential(id: string) {
  return useMutation({
    mutationFn: (body: FetchCredentialRequest) => api.request<FetchCredentialView>("PUT", `${path(id)}/credential`, body),
  });
}
