// The tenant's playbooks: a name's latest version, read by the name, and a
// name's next version, published by a person.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, type PlaybookView, type PublishRequest } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The name's latest version; null when no version has the name. Nothing is
 * read for no name. */
export function usePlaybook(name: string) {
  return useQuery({
    queryKey: keys.playbooks.one(name),
    queryFn: async ({ signal }) => {
      try {
        return await api.get<PlaybookView>(`/v1/playbooks/${encodeURIComponent(name)}`, { signal });
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) return null;
        throw caught;
      }
    },
    enabled: name !== "",
  });
}

export function usePublishPlaybook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PublishRequest) => api.post<PlaybookView>("/v1/playbooks", body, { idempotencyKey: crypto.randomUUID() }),
    onSuccess: (published) => queryClient.setQueryData(keys.playbooks.one(published.name), published),
  });
}
