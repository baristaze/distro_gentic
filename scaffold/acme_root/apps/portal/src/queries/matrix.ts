// The tenant's part of the model matrix: for each model role, the fills it
// may choose, and the fill it chose. A choice is written whole for its role.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FillChoiceView, FillOptionsView, FillView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

const role = (name: string) => `/v1/matrix/choices/${encodeURIComponent(name)}`;

export function useMatrixOptions() {
  return useQuery({
    queryKey: keys.matrix.options,
    queryFn: ({ signal }) => api.get<FillOptionsView[]>("/v1/matrix/options", { signal }),
  });
}

export function useMatrixChoices() {
  return useQuery({
    queryKey: keys.matrix.choices,
    queryFn: ({ signal }) => api.get<FillChoiceView[]>("/v1/matrix/choices", { signal }),
  });
}

/** The fill for a role from the next session on; one of the role's options. */
export function useChoose() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, fill }: { name: string; fill: FillView }) => api.request<FillChoiceView>("PUT", role(name), { fill }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.matrix.choices }),
  });
}

/** The matrix answers the role again. */
export function useDropChoice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.del<void>(role(name)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.matrix.choices }),
  });
}
