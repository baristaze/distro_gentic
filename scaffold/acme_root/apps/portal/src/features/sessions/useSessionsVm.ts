import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { errorMessage } from "../../app/errorMessage";
import { personName } from "../../app/recordModel";
import { useSlot } from "../../app/slot";
import { useAgentSessions, useJoinSession, useTrees } from "../../queries/agentSessions";
import { useMe, useUsers } from "../../queries/tenancy";
import { useNoticesStore } from "../../store/notices";
import { amongOf, listed, listFilterParams, narrowed, readListFilter, serverStatus, sessionRow, treesNeedingYou, type ListFilter, type SessionRow } from "./sessionsModel";

/** Sessions: the person's own first, the ones they made or take part in;
 * or the org's, the org-wide ones any member may join. Each is read in the
 * status the address bar names, a page at a time, and narrowed to the agent,
 * the archived, and words of the title. The filter lives in the address
 * bar, so a link keeps it. */
export function useSessionsVm() {
  const [params, setParams] = useSearchParams();
  const filter = readListFilter(params);
  const list = useAgentSessions(amongOf(filter.view), serverStatus(filter.status));
  const me = useMe();
  const users = useUsers();
  const slot = useSlot();
  const join = useJoinSession();
  const notify = useNoticesStore((s) => s.notify);
  const meId = me.data?.user.id ?? null;
  // "Needs you" reads beneath the parked roots: a sub-agent that waits on a
  // person keeps its root on the list, which holds roots alone.
  const trees = useTrees(filter.status === "needs_you" ? (list.data ?? []) : []);
  const asking = useMemo(() => treesNeedingYou(trees), [trees]);
  const rows = useMemo(
    () => (list.data ? listed(list.data, filter, asking).map((session) => sessionRow(session, meId)) : null),
    // The filter is read from the address bar on every render; its parts are the keys.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [list.data, filter.view, filter.status, filter.kind, filter.archived, filter.query, meId, asking],
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
    /** Who started a session: "You", a member by name, or a former member. */
    starter: (row: SessionRow) => (row.createdBy === meId ? "You" : personName(users.data, row.createdBy)),
    /** The person takes part in a session of the org's: it is on their own list from then on. */
    join: (row: SessionRow) => {
      if (meId === null) return;
      join.mutate(
        { id: row.id, me: meId },
        {
          onSuccess: () => notify(`You joined ${row.title}. It is on your own list now.`),
          onError: (caught) => notify(errorMessage(caught, "You did not join the session."), { tone: "problem" }),
        },
      );
    },
    joining: join.isPending ? join.variables?.id ?? null : null,
    error: list.error,
    hasMore: list.hasNextPage,
    loadingMore: list.isFetchingNextPage,
    loadMore: () => void list.fetchNextPage(),
  };
}

export type SessionsVm = ReturnType<typeof useSessionsVm>;
