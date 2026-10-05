// The tenant's agent sessions: the list, one session and its reads, what a
// person sends it, and its live view. Every read goes through the API under
// the signed-in member's org; a session another org holds answers 404 and
// is never in a list.
import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { useEffect } from "react";
import type {
  AgentSessionPageView,
  AgentSessionView,
  ApprovalView,
  BoundsView,
  CommandProgressView,
  CommandRequest,
  DecisionRequest,
  DeliveryView,
  ExecutionPageView,
  GiveBackRequest,
  HandRunView,
  QuestionView,
  SessionControl,
  SessionStatus,
  SessionModelUsageView,
  StartSessionRequest,
  StepPageView,
  StepView,
  ToolCallPageView,
  ToolCallView,
  ValidationView,
} from "@acme/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The list is read a page at a time on the screen; the history, the tool
 * calls, the runs, and the children are read whole, page after page, at the
 * largest page the server gives. */
export const SESSIONS_PAGE_SIZE = 50;
const WHOLE_PAGE_SIZE = 200;
/** How often an open session's history and its live view are read while it
 * runs: a step that no push names still shows within this. */
export const ACTIVE_POLL_MS = 3000;
const COMMAND_POLL_MS = 1000;

const path = (id: string) => `/v1/agent-sessions/${encodeURIComponent(id)}`;

/** Follows the pages to the end, as the member list does: a page that
 * failed is not asked for again on its own, and the next invalidation
 * starts the walk over. */
export function useWalk(query: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isFetchNextPageError: boolean;
  fetchNextPage: () => Promise<unknown>;
}): boolean {
  const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = query;
  const walking = hasNextPage && !isFetchNextPageError;
  useEffect(() => {
    if (walking && !isFetchingNextPage) void fetchNextPage();
  }, [walking, isFetchingNextPage, fetchNextPage]);
  return walking;
}

export function useAgentSessions(status: SessionStatus | null) {
  const query = useInfiniteQuery({
    queryKey: keys.agentSessions.list(status ?? "any", SESSIONS_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: AgentSessionPageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: String(SESSIONS_PAGE_SIZE) });
      if (status) params.set("status", status);
      if (pageParam) params.set("cursor", pageParam);
      return api.get<AgentSessionPageView>(`/v1/agent-sessions?${params}`, { signal });
    },
  });
  return { ...query, data: query.data?.pages.flatMap((page) => page.items) };
}

/** Every parked session of the org, page after page: a page may hold none
 * parked for a reason a reader counts while later pages do. */
export function useParkedSessions() {
  const query = useInfiniteQuery({
    queryKey: keys.agentSessions.list("parked", WHOLE_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: AgentSessionPageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<AgentSessionPageView>(`/v1/agent-sessions?status=parked&limit=${WHOLE_PAGE_SIZE}${cursor}`, { signal });
    },
  });
  const walking = useWalk(query);
  return { ...query, data: query.data?.pages.flatMap((page) => page.items), isPending: query.isPending || walking };
}

export function useAgentSession(id: string) {
  return useQuery({
    queryKey: keys.agentSessions.one(id),
    queryFn: ({ signal }) => api.get<AgentSessionView>(path(id), { signal }),
  });
}

function bySeq<T extends { seq: number }>(pages: InfiniteData<{ items: T[] }> | undefined): T[] | undefined {
  return pages?.pages.flatMap((page) => page.items);
}

/** The steps after `after`, page after page to the end. */
async function stepsAfter(id: string, after: number, signal: AbortSignal): Promise<StepView[]> {
  const read: StepView[] = [];
  for (let from = after; ; ) {
    const page = await api.get<StepPageView>(`${path(id)}/steps?after_seq=${from}&limit=${WHOLE_PAGE_SIZE}`, { signal });
    read.push(...page.items);
    const last = page.items[page.items.length - 1];
    if (!page.has_more || last === undefined) return read;
    from = last.seq;
  }
}

/** The session's history, whole and in order. A step is written once, so a
 * read after the first asks only for the steps past the last one held: a
 * long session's poll and its pushes read what is new, never the whole
 * history again. While it is active it is read every few seconds as well as
 * on a push. */
export function useSteps(id: string, active: boolean, enabled = true) {
  const queryClient = useQueryClient();
  const queryKey = keys.agentSessions.read(id, "steps");
  return useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const held = queryClient.getQueryData<StepView[]>(queryKey) ?? [];
      const fresh = await stepsAfter(id, held[held.length - 1]?.seq ?? 0, signal);
      return fresh.length === 0 ? held : [...held, ...fresh];
    },
    refetchInterval: active ? ACTIVE_POLL_MS : false,
    enabled,
  });
}

export function useToolCalls(id: string, active: boolean, enabled = true) {
  const query = useInfiniteQuery({
    queryKey: keys.agentSessions.read(id, "tool_calls"),
    initialPageParam: 0,
    getNextPageParam: (last: ToolCallPageView) => (last.has_more ? last.items[last.items.length - 1]?.seq : undefined),
    queryFn: ({ pageParam, signal }) =>
      api.get<ToolCallPageView>(`${path(id)}/tool-calls?after_seq=${pageParam}&limit=${WHOLE_PAGE_SIZE}`, { signal }),
    refetchInterval: active ? ACTIVE_POLL_MS : false,
    enabled,
  });
  const walking = useWalk(query);
  return { ...query, data: bySeq<ToolCallView>(query.data), isPending: query.isPending || walking };
}

function useCursorWalk<T>(id: string, part: string, route: string, enabled: boolean) {
  const query = useInfiniteQuery({
    queryKey: keys.agentSessions.read(id, part),
    initialPageParam: null as string | null,
    getNextPageParam: (last: { items: T[]; next_cursor: string | null }) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<{ items: T[]; next_cursor: string | null }>(`${path(id)}/${route}?limit=${WHOLE_PAGE_SIZE}${cursor}`, {
        signal,
      });
    },
    enabled,
  });
  const walking = useWalk(query);
  return { ...query, data: query.data?.pages.flatMap((page) => page.items), isPending: query.isPending || walking };
}

export function useExecutions(id: string, enabled = true) {
  return useCursorWalk<ExecutionPageView["items"][number]>(id, "executions", "executions", enabled);
}

export function useChildren(id: string, enabled = true) {
  return useCursorWalk<AgentSessionView>(id, "children", "children", enabled);
}

function useRead<T>(id: string, part: string, route: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.agentSessions.read(id, part),
    queryFn: ({ signal }) => api.get<T>(`${path(id)}/${route}`, { signal }),
    enabled,
  });
}

export const useQuestions = (id: string, enabled = true) => useRead<QuestionView[]>(id, "questions", "questions", enabled);
export const useApprovals = (id: string, enabled = true) => useRead<ApprovalView[]>(id, "approvals", "approvals", enabled);
export const useBounds = (id: string, enabled = true) => useRead<BoundsView>(id, "bounds", "bounds", enabled);
export const useUsage = (id: string, enabled = true) => useRead<SessionModelUsageView>(id, "usage", "usage", enabled);
export const useDelivery = (id: string, enabled = true) => useRead<DeliveryView>(id, "delivery", "delivery", enabled);
export const useValidations = (id: string, enabled = true) =>
  useRead<ValidationView[]>(id, "validations", "validations", enabled);

/** A command run by hand, read until it is done. */
export function useCommandProgress(id: string, key: string | null) {
  return useQuery({
    queryKey: keys.agentSessions.command(id, key ?? ""),
    queryFn: ({ signal }) =>
      api.get<CommandProgressView>(`${path(id)}/control/commands/${encodeURIComponent(key!)}`, { signal }),
    enabled: key !== null,
    refetchInterval: (query) => (query.state.data && ["done", "interrupted"].includes(query.state.data.state) ? false : COMMAND_POLL_MS),
  });
}

export function useStartSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StartSessionRequest) => api.post<AgentSessionView>("/v1/agent-sessions", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.agentSessions.lists }),
  });
}

/** A message to a session the caller names at the call: Home sends the
 * prompt to the session it has just started. */
export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => api.post<StepView>(`${path(id)}/messages`, { text }),
    onSettled: (_step, _error, { id }) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.agentSessions.one(id) }),
        queryClient.invalidateQueries({ queryKey: keys.agentSessions.lists }),
      ]),
  });
}

/** What a person sends a session: each answers with what was stored, and the
 * session's reads are read again. */
export function useSessionActions(id: string) {
  const queryClient = useQueryClient();
  const settled = () => queryClient.invalidateQueries({ queryKey: keys.agentSessions.one(id) });
  const listed = () =>
    Promise.all([settled(), queryClient.invalidateQueries({ queryKey: keys.agentSessions.lists })]);
  return {
    message: useMutation({
      mutationFn: (text: string) => api.post<StepView>(`${path(id)}/messages`, { text }),
      onSettled: settled,
    }),
    control: useMutation({
      mutationFn: (body: { command: SessionControl; request_seq?: number }) => api.post<StepView>(`${path(id)}/controls`, body),
      onSettled: settled,
    }),
    decide: useMutation({
      mutationFn: ({ seq, ...body }: { seq: number } & Pick<DecisionRequest, "approve"> & Partial<DecisionRequest>) =>
        api.post<StepView>(`${path(id)}/calls/${seq}/decision`, body),
      onSettled: settled,
    }),
    takeControl: useMutation({
      mutationFn: () => api.post<AgentSessionView>(`${path(id)}/control`),
      onSettled: settled,
    }),
    runCommand: useMutation({
      mutationFn: (body: Pick<CommandRequest, "argv"> & Partial<CommandRequest>) => api.post<HandRunView>(`${path(id)}/control/commands`, body),
      onSettled: settled,
    }),
    giveBack: useMutation({
      mutationFn: (body: Pick<GiveBackRequest, "summary"> & Partial<GiveBackRequest>) => api.post<AgentSessionView>(`${path(id)}/control/give-back`, body),
      onSettled: settled,
    }),
    archive: useMutation({
      mutationFn: () => api.post<AgentSessionView>(`${path(id)}/archive`),
      onSettled: listed,
    }),
    restore: useMutation({
      mutationFn: () => api.post<AgentSessionView>(`${path(id)}/restore`),
      onSettled: listed,
    }),
  };
}
