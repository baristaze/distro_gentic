import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useSlot } from "../../app/slot";
import { useAgentSessions } from "../../queries/agentSessions";
import { useMe } from "../../queries/tenancy";
import { listed, listFilterParams, narrowed, readListFilter, serverStatus, sessionRow, type ListFilter } from "./sessionsModel";

/** All sessions: the tenant's sessions in the status the address bar names,
 * a page at a time, narrowed to whose they are, the agent, the archived,
 * and words of the title. The filter lives in the address bar, so a link
 * keeps it. */
export function useSessionsVm() {
  const [params, setParams] = useSearchParams();
  const filter = readListFilter(params);
  const list = useAgentSessions(serverStatus(filter.status));
  const me = useMe();
  const slot = useSlot();
  const meId = me.data?.user.id ?? null;
  const rows = useMemo(
    () => (list.data ? listed(list.data, filter, meId).map(sessionRow) : null),
    // The filter is read from the address bar on every render; its parts are the keys.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [list.data, filter.status, filter.owner, filter.kind, filter.archived, filter.query, meId],
  );
  const kinds = useMemo(() => {
    const named = slot.agents.map((agent) => ({ value: agent.kind, label: agent.label }));
    const seen = [...new Set((list.data ?? []).map((session) => session.kind))]
      .filter((kind) => !named.some((agent) => agent.value === kind))
      .map((kind) => ({ value: kind, label: kind }));
    return [{ value: "", label: "Any agent" }, ...named, ...seen];
  }, [slot.agents, list.data]);
  return {
    filter,
    setFilter: (change: Partial<ListFilter>) => setParams(listFilterParams({ ...filter, ...change }), { replace: true }),
    narrowed: narrowed(filter) || filter.status !== "any",
    kinds,
    rows,
    error: list.error,
    hasMore: list.hasNextPage,
    loadingMore: list.isFetchingNextPage,
    loadMore: () => void list.fetchNextPage(),
  };
}
