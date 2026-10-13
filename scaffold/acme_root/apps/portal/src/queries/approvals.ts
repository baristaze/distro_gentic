// The calls the sessions a person sees hold for a decision. Each session's
// held calls are read on its own route, which shows a sub-agent's as its
// root is seen, so a call a sub-agent holds is named as its root's are. A
// call is decided on its session's own page.
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import type { ApprovalView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

const toolsOf = (ids: readonly string[]) => (read: readonly { data?: ApprovalView[] }[]) => {
  const held = new Map<string, string>();
  read.forEach((one, index) => {
    const first = one.data?.[0];
    if (first) held.set(ids[index]!, first.tool);
  });
  return held;
};

/** The tool each of these sessions holds for a decision, read only for the
 * sessions that hold one, each under the key its own page reads it by, so a
 * push about one reads it again. */
export function useHeldTools(sessionIds: readonly string[]) {
  const ids = [...new Set(sessionIds)].sort();
  const key = ids.join(" ");
  // One combine for as long as the ids are the same, so the map is made once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const combine = useMemo(() => toolsOf(ids), [key]);
  const data = useQueries({
    queries: ids.map((id) => ({
      queryKey: keys.agentSessions.read(id, "approvals"),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.get<ApprovalView[]>(`/v1/agent-sessions/${encodeURIComponent(id)}/approvals`, { signal }),
    })),
    combine,
  });
  return { data };
}
