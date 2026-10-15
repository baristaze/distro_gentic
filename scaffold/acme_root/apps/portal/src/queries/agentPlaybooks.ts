// The tenant's agent playbooks: a name's latest version, read by the name, and a
// name's next version, published by a person.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type agent_playbooks } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The name's latest version; null when no version has the name. Nothing is
 * read for no name. */
export function useAgentPlaybook(name: string) {
  return useQuery({
    queryKey: keys.agentPlaybooks.one(name),
    queryFn: async ({ signal }) => {
      try {
        return await api.get<agent_playbooks.AgentPlaybookView>(`/v1/agent-playbooks/${encodeURIComponent(name)}`, { signal });
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) return null;
        throw caught;
      }
    },
    enabled: name !== "",
  });
}

export function usePublishAgentPlaybook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: agent_playbooks.PublishRequest) => api.post<agent_playbooks.AgentPlaybookView>("/v1/agent-playbooks", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: (published) => queryClient.setQueryData(keys.agentPlaybooks.one(published.name), published),
  });
}
