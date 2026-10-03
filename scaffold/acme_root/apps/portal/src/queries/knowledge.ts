// The tenant's knowledge: the entries in a state, one entry, and an entry a
// person writes, edits on the version they read, or reviews.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { KnowledgeRequest, KnowledgeStatus, KnowledgeView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

const PAGE_SIZE = 200;
const path = (id: string) => `/v1/knowledge/${encodeURIComponent(id)}`;

export function useKnowledge(status: KnowledgeStatus) {
  return useQuery({
    queryKey: keys.knowledge.list(status, PAGE_SIZE),
    queryFn: async ({ signal }) => {
      const read: KnowledgeView[] = [];
      for (let after: string | null = null; ; ) {
        const cursor: string = after ? `&after=${encodeURIComponent(after)}` : "";
        const page = await api.get<KnowledgeView[]>(`/v1/knowledge?status=${status}&limit=${PAGE_SIZE}${cursor}`, { signal });
        read.push(...page);
        const last = page[page.length - 1];
        if (page.length < PAGE_SIZE || last === undefined) return read;
        after = last.id;
      }
    },
  });
}

export function useEntry(id: string) {
  return useQuery({
    queryKey: keys.knowledge.one(id),
    queryFn: ({ signal }) => api.get<KnowledgeView>(path(id), { signal }),
  });
}

function useSaved() {
  const queryClient = useQueryClient();
  return (saved: KnowledgeView) => {
    queryClient.setQueryData(keys.knowledge.one(saved.id), saved);
    return queryClient.invalidateQueries({ queryKey: [...keys.knowledge.all, "list"] });
  };
}

export function useWriteEntry() {
  const onSuccess = useSaved();
  return useMutation({
    mutationFn: (body: KnowledgeRequest) => api.post<KnowledgeView>("/v1/knowledge", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess,
  });
}

/** The entry as edited, on the version the person read: a version moved on
 * since is refused, never overwritten. */
export function useEditEntry(id: string) {
  const onSuccess = useSaved();
  return useMutation({
    mutationFn: ({ body, version }: { body: KnowledgeRequest; version: number }) =>
      api.request<KnowledgeView>("PUT", path(id), body, { ifMatch: version }),
    onSuccess,
  });
}

export function useReviewEntry(id: string) {
  const onSuccess = useSaved();
  return useMutation({
    mutationFn: (keep: boolean) => api.post<KnowledgeView>(`${path(id)}/review`, { keep }),
    onSuccess,
  });
}
