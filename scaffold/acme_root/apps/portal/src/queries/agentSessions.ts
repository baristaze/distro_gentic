// The tenant's agent sessions: the lists, one session and its reads, what a
// person sends it, and its live view. Every read goes through the API under
// the signed-in member's org; a session another org holds answers 404 and
// is never in a list. A list is the person's own (`mine`: the ones they made
// or take part in) or every one they see (`visible`).
import { useInfiniteQuery, useMutation, useQueries, useQuery, useQueryClient, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import type {
  AgentSessionPageView,
  Among,
  AgentSessionView,
  ApprovalView,
  BoundsView,
  CommandProgressView,
  CommandRequest,
  DecisionRequest,
  WorkProductView,
  ExecutionPageView,
  ControlGiveBackRequest,
  HandRunView,
  InvocationView,
  InvokeRequest,
  PrincipalRequest,
  QuestionView,
  AgentSessionControl,
  AgentSessionStatus,
  SessionModelUsageView,
  StartAgentSessionRequest,
  AgentStepPageView,
  AgentStepView,
  ToolCallPageView,
  ToolCallView,
  ValidationView,
  Visibility,
  VisibilityRequest,
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

export function useAgentSessions(among: Among, status: AgentSessionStatus | null) {
  const query = useInfiniteQuery({
    queryKey: keys.agentSessions.list(among, status ?? "any", SESSIONS_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: AgentSessionPageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ among, limit: String(SESSIONS_PAGE_SIZE) });
      if (status) params.set("status", status);
      if (pageParam) params.set("cursor", pageParam);
      return api.get<AgentSessionPageView>(`/v1/agent-sessions?${params}`, { signal });
    },
  });
  return { ...query, data: query.data?.pages.flatMap((page) => page.items) };
}

/** Every parked session of the list, page after page: a page may hold none
 * parked for a reason a reader counts while later pages do. */
export function useParkedSessions(among: Among) {
  const query = useInfiniteQuery({
    queryKey: keys.agentSessions.list(among, "parked", WHOLE_PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last: AgentSessionPageView) => last.next_cursor,
    queryFn: ({ pageParam, signal }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<AgentSessionPageView>(`/v1/agent-sessions?among=${among}&status=parked&limit=${WHOLE_PAGE_SIZE}${cursor}`, { signal });
    },
  });
  const walking = useWalk(query);
  return { ...query, data: query.data?.pages.flatMap((page) => page.items), isPending: query.isPending || walking };
}

/** Whether a session's tree may still change: it works or waits, and its
 * sub-agents with it. */
const working = (session: Pick<AgentSessionView, "status" | "archived_at">) => session.archived_at === null && session.status !== "idle";

/** Every sub-agent beneath `rootId`, read through the children route,
 * which shows a tree only to one who sees its root. A sub-agent that is
 * done is not read beneath: none of its own works on. */
async function treeBeneath(rootId: string, signal: AbortSignal): Promise<AgentSessionView[]> {
  const read: AgentSessionView[] = [];
  const seen = new Set([rootId]);
  for (const queue = [rootId]; queue.length > 0; ) {
    const parent = queue.shift()!;
    for (let cursor: string | null = null; ; ) {
      const after: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
      const page: AgentSessionPageView = await api.get<AgentSessionPageView>(`${path(parent)}/children?limit=${WHOLE_PAGE_SIZE}${after}`, { signal });
      for (const child of page.items) {
        if (seen.has(child.id)) continue;
        seen.add(child.id);
        read.push(child);
        if (working(child)) queue.push(child.id);
      }
      if (!page.next_cursor) break;
      cursor = page.next_cursor;
    }
  }
  return read;
}

const treesOf = (read: readonly { data?: AgentSessionView[] }[]) => read.flatMap((one) => one.data ?? []);

/** The sub-agents of the roots that work or wait, at every depth: a list
 * holds roots alone, and a sub-agent that needs a person lifts its tree.
 * Each tree is read under the lists' key, so a push about any session reads
 * it again with them. */
export function useTrees(roots: readonly AgentSessionView[]): AgentSessionView[] {
  const ids = [...new Set(roots.filter((root) => root.parent_id === null && working(root)).map((root) => root.id))];
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: [...keys.agentSessions.lists, "tree", id] as const,
      queryFn: ({ signal }: { signal: AbortSignal }) => treeBeneath(id, signal),
    })),
    combine: treesOf,
  });
}

const sessionQuery = (id: string, enabled: boolean) => ({
  queryKey: keys.agentSessions.one(id),
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<AgentSessionView>(path(id), { signal }),
  enabled,
});

export function useAgentSession(id: string, enabled = true) {
  return useQuery(sessionQuery(id, enabled));
}

const recordsOf = (read: readonly { data?: AgentSessionView }[]) => read.map((one) => one.data);

/** Several sessions' records, in their order, each the read its own page
 * makes, so a push about one reads it again. One array for as long as no
 * record changes. */
export function useSessionRecords(ids: readonly string[]): readonly (AgentSessionView | undefined)[] {
  return useQueries({ queries: ids.map((id) => sessionQuery(id, true)), combine: recordsOf });
}

function bySeq<T extends { seq: number }>(pages: InfiniteData<{ items: T[] }> | undefined): T[] | undefined {
  return pages?.pages.flatMap((page) => page.items);
}

/** The steps after `after`, page after page to the end. */
async function stepsAfter(id: string, after: number, signal: AbortSignal): Promise<AgentStepView[]> {
  const read: AgentStepView[] = [];
  for (let from = after; ; ) {
    const page = await api.get<AgentStepPageView>(`${path(id)}/steps?after_seq=${from}&limit=${WHOLE_PAGE_SIZE}`, { signal });
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
function stepsQuery(queryClient: QueryClient, id: string, active: boolean, enabled: boolean) {
  const queryKey = keys.agentSessions.read(id, "steps");
  return {
    queryKey,
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const held = queryClient.getQueryData<AgentStepView[]>(queryKey) ?? [];
      const fresh = await stepsAfter(id, held[held.length - 1]?.seq ?? 0, signal);
      return fresh.length === 0 ? held : [...held, ...fresh];
    },
    refetchInterval: active ? ACTIVE_POLL_MS : (false as const),
    enabled,
  };
}

export function useSteps(id: string, active: boolean, enabled = true) {
  return useQuery(stepsQuery(useQueryClient(), id, active, enabled));
}

const stepsOf = (read: readonly { data?: AgentStepView[] }[]) => read.map((one) => one.data);

/** The histories of a session's sub-agents, in their order, each read as
 * its own page reads it, so opening one shows what is already held: what
 * each does now shows on its parent's page. A child that is done is not
 * read again. One array for as long as no history changes. */
export function useChildSteps(children: readonly AgentSessionView[]): readonly (AgentStepView[] | undefined)[] {
  const queryClient = useQueryClient();
  const works = (child: AgentSessionView) => child.archived_at === null && child.status !== "idle";
  return useQueries({ queries: children.map((child) => stepsQuery(queryClient, child.id, works(child), works(child))), combine: stepsOf });
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
  // One list for as long as no page changes, so what is made from it is made once.
  const pages = query.data;
  const data = useMemo(() => pages?.pages.flatMap((page) => page.items), [pages]);
  return { ...query, data, isPending: query.isPending || walking };
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

/** How many steps before a park its question is looked for in. */
const ASKED_WINDOW = 8;

/** The steps that led to a session's park on its person's answer, where
 * the agent asked its question: a short read once the park is known, never
 * the whole history. Empty when it waits on no answer. */
export function useStepsBeforeAnswer(id: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.agentSessions.read(id, "asked"),
    queryFn: async ({ signal }) => {
      const parks = await api.get<QuestionView[]>(`${path(id)}/questions`, { signal });
      const park = parks.find((one) => one.unlock === "answer");
      if (!park) return [];
      const after = Math.max(0, park.seq - ASKED_WINDOW);
      return (await api.get<AgentStepPageView>(`${path(id)}/steps?after_seq=${after}&limit=${ASKED_WINDOW}`, { signal })).items;
    },
    enabled,
  });
}

export const useQuestions = (id: string, enabled = true) => useRead<QuestionView[]>(id, "questions", "questions", enabled);
export const useApprovals = (id: string, enabled = true) => useRead<ApprovalView[]>(id, "approvals", "approvals", enabled);
export const useBounds = (id: string, enabled = true) => useRead<BoundsView>(id, "bounds", "bounds", enabled);
export const useUsage = (id: string, enabled = true) => useRead<SessionModelUsageView>(id, "usage", "usage", enabled);
export const useWorkProduct = (id: string, enabled = true) => useRead<WorkProductView>(id, "work_product", "work-product", enabled);
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
    mutationFn: (body: StartAgentSessionRequest) => api.post<AgentSessionView>("/v1/agent-sessions", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.agentSessions.lists }),
  });
}

/** A member joins an org-wide session, from a list: they take part from
 * then on, and it is on their own list. */
export function useJoinSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, me }: { id: string; me: string }) =>
      api.request<AgentSessionView>("PUT", `${path(id)}/participants/${encodeURIComponent(me)}`),
    onSettled: (_session, _error, { id }) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.agentSessions.one(id) }),
        queryClient.invalidateQueries({ queryKey: keys.agentSessions.lists }),
      ]),
  });
}

/** A message to a session the caller names at the call: Home sends the
 * prompt to the session it has just started. */
export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => api.post<AgentStepView>(`${path(id)}/messages`, { text }),
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
      mutationFn: (text: string) => api.post<AgentStepView>(`${path(id)}/messages`, { text }),
      onSettled: settled,
    }),
    control: useMutation({
      mutationFn: (body: { command: AgentSessionControl; request_seq?: number }) => api.post<AgentStepView>(`${path(id)}/controls`, body),
      onSettled: settled,
    }),
    decide: useMutation({
      mutationFn: ({ seq, ...body }: { seq: number } & Pick<DecisionRequest, "approve"> & Partial<DecisionRequest>) =>
        api.post<AgentStepView>(`${path(id)}/calls/${seq}/decision`, body),
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
      mutationFn: (body: Pick<ControlGiveBackRequest, "summary"> & Partial<ControlGiveBackRequest>) => api.post<AgentSessionView>(`${path(id)}/control/give-back`, body),
      onSettled: settled,
    }),
    /** A person takes part: a member joins an org-wide session, and its
     * creator adds a member, to a private one too. */
    join: useMutation({
      mutationFn: (person: string) => api.request<AgentSessionView>("PUT", `${path(id)}/participants/${encodeURIComponent(person)}`),
      onSettled: listed,
    }),
    /** Its creator switches who sees it. */
    share: useMutation({
      mutationFn: (visibility: Visibility) => api.request<AgentSessionView>("PUT", `${path(id)}/visibility`, { visibility } satisfies VisibilityRequest),
      onSettled: listed,
    }),
    /** The steer moves: its steerer hands it to a participant, or, with
     * no one named, the caller takes a lapsed steerer's. */
    steer: useMutation({
      mutationFn: (steerer: string | null) =>
        api.request<AgentSessionView>("PUT", `${path(id)}/principal`, steerer === null ? undefined : ({ steerer } satisfies PrincipalRequest)),
      onSettled: listed,
    }),
    archive: useMutation({
      mutationFn: () => api.post<AgentSessionView>(`${path(id)}/archive`),
      onSettled: listed,
    }),
    restore: useMutation({
      mutationFn: () => api.post<AgentSessionView>(`${path(id)}/restore`),
      onSettled: listed,
    }),
    /** An agent playbook's latest version brought into the session: its brief
     * arrives as the person's message, and its gates hold from now on. */
    invoke: useMutation({
      mutationFn: (name: string) =>
        api.post<InvocationView>(`/v1/agent-playbooks/${encodeURIComponent(name)}/invocations`, { agent_session_id: id } satisfies InvokeRequest, {
          idempotencyKey: crypto.randomUUID(),
        }),
      onSettled: settled,
    }),
  };
}
