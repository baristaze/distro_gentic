// The tenant's own keys to its model providers. A key's value goes in on a
// save and never comes back: the reads answer the record alone, who added
// it, when, its state, and when it was last used.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ProviderKeyView, ProviderName } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The largest page the server gives: every provider's live key and the
 * ones rotated out before it. */
const PAGE_SIZE = 200;

export function useProviderKeys() {
  return useQuery({
    queryKey: keys.providerKeys.list(PAGE_SIZE),
    queryFn: ({ signal }) => api.get<ProviderKeyView[]>(`/v1/provider-keys?limit=${PAGE_SIZE}`, { signal }),
  });
}

/** Probed, then saved as the provider's live key; the one before it rotates
 * out. The options a tenant may choose follow the keys it holds. */
export function useSaveKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, value }: { provider: ProviderName; value: string }) =>
      api.request<ProviderKeyView>("PUT", `/v1/provider-keys/${encodeURIComponent(provider)}`, { value }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.providerKeys.all }),
        queryClient.invalidateQueries({ queryKey: keys.matrix.all }),
      ]),
  });
}
