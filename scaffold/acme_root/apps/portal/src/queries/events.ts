// The event stream is replayed, not subscribed to: the realtime provider
// asks for everything after the last seq it saw, one page at a time. The
// audit reads the same stream, oldest kept first, a page at a time.
import { useInfiniteQuery } from "@tanstack/react-query";
import { ApiError, type EventView } from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

export const EVENTS_PAGE = 200;
export const AUDIT_PAGE = 100;

export function fetchEventsAfter(afterSeq: number, limit = EVENTS_PAGE): Promise<EventView[]> {
  return api.get<EventView[]>(`/v1/events?after_seq=${afterSeq}&limit=${limit}`);
}

/** The seq a `stream_truncated` refusal says the stream is kept after; null
 * for any other failure. */
function keptAfter(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.code !== "stream_truncated") return null;
  return error.stream?.floor ?? null;
}

/** A page of the org's events after `afterSeq`. Where the maintenance trim
 * has raised the floor past it, the events up to the floor are gone, and
 * the page is read on from the floor instead. */
async function auditPage(afterSeq: number, signal: AbortSignal): Promise<EventView[]> {
  for (let after = afterSeq; ; ) {
    try {
      return await api.get<EventView[]>(`/v1/events?after_seq=${after}&limit=${AUDIT_PAGE}`, { signal });
    } catch (caught) {
      const floor = keptAfter(caught);
      if (floor === null || floor <= after) throw caught;
      after = floor;
    }
  }
}

/** The org's events from the oldest kept, each page after the last seq the
 * one before held; a short page is the last. The route reads only forward
 * from a seq, so the oldest kept come first. */
export function useAuditEvents() {
  const query = useInfiniteQuery({
    queryKey: keys.audit.list(AUDIT_PAGE),
    initialPageParam: 0,
    getNextPageParam: (last: EventView[]) => (last.length < AUDIT_PAGE ? undefined : last[last.length - 1]!.seq),
    queryFn: ({ pageParam, signal }) => auditPage(pageParam, signal),
  });
  return { ...query, data: query.data?.pages.flat() };
}
