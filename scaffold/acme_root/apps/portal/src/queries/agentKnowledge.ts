// The tenant's agent knowledge: the entries in a state, one entry, and an entry a
// person writes, edits on the version they read, or reviews.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { agent_knowledge } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

const PAGE_SIZE = 200;
const path = (id: string) => `/v1/agent-knowledge/${encodeURIComponent(id)}`;

export function useAgentKnowledge(status: agent_knowledge.AgentKnowledgeStatus) {
  return useQuery({
    queryKey: keys.agentKnowledge.list(status, PAGE_SIZE),
    queryFn: async ({ signal }) => {
      const read: agent_knowledge.AgentKnowledgeView[] = [];
      for (let after: string | null = null; ; ) {
        const cursor: string = after ? `&after=${encodeURIComponent(after)}` : "";
        const page = await api.get<agent_knowledge.AgentKnowledgeView[]>(`/v1/agent-knowledge?status=${status}&limit=${PAGE_SIZE}${cursor}`, { signal });
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
    queryKey: keys.agentKnowledge.one(id),
    queryFn: ({ signal }) => api.get<agent_knowledge.AgentKnowledgeView>(path(id), { signal }),
  });
}

function useSaved() {
  const queryClient = useQueryClient();
  return (saved: agent_knowledge.AgentKnowledgeView) => {
    queryClient.setQueryData(keys.agentKnowledge.one(saved.id), saved);
    return queryClient.invalidateQueries({ queryKey: [...keys.agentKnowledge.all, "list"] });
  };
}

export function useWriteEntry() {
  const onSuccess = useSaved();
  return useMutation({
    mutationFn: (body: agent_knowledge.AgentKnowledgeRequest) => api.post<agent_knowledge.AgentKnowledgeView>("/v1/agent-knowledge", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess,
  });
}

/** The entry as edited, on the version the person read: a version moved on
 * since is refused, never overwritten. */
export function useEditEntry(id: string) {
  const onSuccess = useSaved();
  return useMutation({
    mutationFn: ({ body, version }: { body: agent_knowledge.AgentKnowledgeRequest; version: number }) =>
      api.request<agent_knowledge.AgentKnowledgeView>("PUT", path(id), body, { ifMatch: version }),
    onSuccess,
  });
}

export function useReviewEntry(id: string) {
  const onSuccess = useSaved();
  return useMutation({
    mutationFn: (keep: boolean) => api.post<agent_knowledge.AgentKnowledgeView>(`${path(id)}/review`, { keep }),
    onSuccess,
  });
}
