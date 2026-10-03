// The event stream is replayed, not subscribed to: the realtime provider
// asks for everything after the last seq it saw, one page at a time. The
// audit reads the same stream, oldest first, a page at a time.
import { useInfiniteQuery } from "@tanstack/react-query";
import type { EventView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

export const EVENTS_PAGE = 200;
export const AUDIT_PAGE = 100;

export function fetchEventsAfter(afterSeq: number, limit = EVENTS_PAGE): Promise<EventView[]> {
  return api.get<EventView[]>(`/v1/events?after_seq=${afterSeq}&limit=${limit}`);
}

/** The org's events from the first, each page after the last seq the one
 * before held; a short page is the last. */
export function useAuditEvents() {
  const query = useInfiniteQuery({
    queryKey: keys.audit.list(AUDIT_PAGE),
    initialPageParam: 0,
    getNextPageParam: (last: EventView[]) => (last.length < AUDIT_PAGE ? undefined : last[last.length - 1]!.seq),
    queryFn: ({ pageParam, signal }) => api.get<EventView[]>(`/v1/events?after_seq=${pageParam}&limit=${AUDIT_PAGE}`, { signal }),
  });
  return { ...query, data: query.data?.pages.flat() };
}
