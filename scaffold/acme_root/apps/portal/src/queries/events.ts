// The event stream is replayed, not subscribed to: the realtime provider
// asks for everything after the last seq it saw, one page at a time. The
// audit reads the same stream back from the head, newest first.
import { useInfiniteQuery } from "@tanstack/react-query";
import type { EventView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

export const EVENTS_PAGE = 200;
export const AUDIT_PAGE = 100;

export function fetchEventsAfter(afterSeq: number, limit = EVENTS_PAGE): Promise<EventView[]> {
  return api.get<EventView[]>(`/v1/events?after_seq=${afterSeq}&limit=${limit}`);
}

/** A page of the org's newest events below `beforeSeq`, newest first;
 * from the head when it is null. */
function auditPage(beforeSeq: number | null, signal: AbortSignal): Promise<EventView[]> {
  const below = beforeSeq === null ? "" : `&before_seq=${beforeSeq}`;
  return api.get<EventView[]>(`/v1/events/recent?limit=${AUDIT_PAGE}${below}`, { signal });
}

/** The org's events from the newest, each page below the oldest seq the one
 * before held, back to the floor; a short page is the last. */
export function useAuditEvents() {
  const query = useInfiniteQuery({
    queryKey: keys.audit.list(AUDIT_PAGE),
    initialPageParam: null as number | null,
    getNextPageParam: (last: EventView[]) => (last.length < AUDIT_PAGE ? undefined : last[last.length - 1]!.seq),
    queryFn: ({ pageParam, signal }) => auditPage(pageParam, signal),
  });
  return { ...query, data: query.data?.pages.flat() };
}
