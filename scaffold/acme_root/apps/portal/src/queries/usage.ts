// The tenant's usage: each budget with what its current window holds and
// spent, a page at a time.
import { useInfiniteQuery } from "@tanstack/react-query";
import type { UsagePageView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

export const USAGE_PAGE_SIZE = 50;

export function useUsage() {
  const query = useInfiniteQuery({
    queryKey: keys.usage.list(USAGE_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: UsagePageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<UsagePageView>(`/v1/usage?limit=${USAGE_PAGE_SIZE}${cursor}`, { signal });
    },
  });
  return { ...query, data: query.data?.pages.flatMap((page) => page.items) };
}
