// The calls the org's sessions hold for a person's decision, a page at a
// time. A call is decided on its session's own page.
import { useInfiniteQuery } from "@tanstack/react-query";
import type { ApprovalPageView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

export const APPROVALS_PAGE_SIZE = 50;

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
  return { ...query, data: query.data?.pages.flatMap((page) => page.items) };
}
