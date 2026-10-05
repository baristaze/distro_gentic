// The calls the org's sessions hold for a person's decision, read whole. A
// page covers a page of parked sessions, so one may hold no call while a
// later one does. A call is decided on its session's own page.
import { useQuery } from "@tanstack/react-query";
import type { ApprovalPageView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

export const APPROVALS_PAGE_SIZE = 50;

/** The tool each of these sessions holds for a decision, read only while one
 * holds a call: the list of the sessions is the key, so a session that comes
 * to hold one reads the calls again, and none read none. */
export function useHeldTools(sessionIds: readonly string[]) {
  const ids = [...sessionIds].sort();
  return useQuery({
    queryKey: [...keys.approvals.all, "held", ...ids],
    enabled: ids.length > 0,
    queryFn: async ({ signal }) => {
      const held = new Map<string, string>();
      for (let cursor: string | null = null; ; ) {
        const after: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
        const page: ApprovalPageView = await api.get<ApprovalPageView>(`/v1/approvals?limit=${APPROVALS_PAGE_SIZE}${after}`, { signal });
        for (const call of page.items) if (!held.has(call.session_id)) held.set(call.session_id, call.tool);
        if (!page.next_cursor) return held;
        cursor = page.next_cursor;
      }
    },
  });
}
