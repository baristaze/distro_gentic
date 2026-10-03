// The calls the org's sessions hold for a person's decision, read whole. A
// page covers a page of parked sessions, so one may hold no call while a
// later one does. A call is decided on its session's own page.
import { useInfiniteQuery } from "@tanstack/react-query";
import type { ApprovalPageView } from "@acme/client";
import { api } from "../app/api";
import { useWalk } from "./agentSessions";
import { keys } from "./keys";

export const APPROVALS_PAGE_SIZE = 50;

/** Every held call, page after page; pending until the walk ends, so an
 * empty first page never reads as an empty inbox. */
export function useOrgApprovals() {
  const query = useInfiniteQuery({
    queryKey: keys.approvals.list(APPROVALS_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: ApprovalPageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<ApprovalPageView>(`/v1/approvals?limit=${APPROVALS_PAGE_SIZE}${cursor}`, { signal });
    },
  });
  const walking = useWalk(query);
  return { ...query, data: query.data?.pages.flatMap((page) => page.items), isPending: query.isPending || walking };
}
