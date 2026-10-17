// Envelopes route into the query cache, never into components. An
// `entity_changed` push names an entity inside its kind
// (`<namespace>.<entity>.<action>`) and one record of it. For an entity with
// a hint reader, the push is a hint: the reader reads that one record and
// places it (`hints.ts`). Any other push invalidates the queries that carry
// its entity: by convention the queries whose key starts with the entity
// name, and by the table below where the entity is read through another
// query, or through none.
import type { QueryClient, QueryKey } from "@tanstack/react-query";
import { keys } from "../queries/keys";
import { entityOf, isEntityChanged, type Envelope, type ChangeEventEnvelope } from "./envelopes";
import type { Hints } from "./hints";

export interface RouteOutcome {
  invalidated: QueryKey[];
  /** An entity whose reader took a push as a hint, when one did. */
  hinted?: string;
}

/** The hint reader of each entity read one record at a time. */
export type HintReaders = Readonly<Record<string, Hints>>;

// Entities the convention does not reach on its own. A membership is read as
// the role and the permissions inside `me`, as the role in the person's list
// of places the org chip reads, and as the role beside each member in
// Settings; a user is read twice, as a row of the member list and as the name
// and the email in `me`, so a user push reaches both: its reader places the
// member in both (`userCache.ts`). A revoked auth session is nobody's
// query: this auth session's own revocation arrives as a 4401 close, not as
// a push. No screen reads an orchestration's record; a screen that does
// keys its queries under the entity and drops its line here. A command run
// by hand names its run, which only the person who sent it reads, every
// second until it ends; the agent sessions' pushes are routed below.
const CARRIED_BY: Readonly<Record<string, readonly QueryKey[]>> = {
  auth_session: [],
  membership: [keys.me, keys.myMemberships.all, keys.memberships.all],
  orchestration: [],
  user: [keys.users.all, keys.me],
  // A copy adds its entries below this line.
  command: [],
};

/** The pushes that name one agent session: its record changed, its stream
 * opened or completed, or a hand-over was taken or given back. */
const OF_A_SESSION = new Set(["agent_session", "stream", "control"]);

function holds(data: unknown, id: string): boolean {
  const pages = (data as { pages?: { items?: { id?: string }[] }[] } | undefined)?.pages ?? [];
  return pages.some((page) => (page.items ?? []).some((item) => item.id === id));
}

/** A push that names a session reaches that session's reads alone, never
 * another session's: an open page of a long session is not read again for
 * every push of its org. Its record's change also reaches the lists, which
 * show each session's status, and the lists of children that hold it (every
 * list of children, when the session is new and may be one). */
function sessionTargets(queryClient: QueryClient, entity: string, action: string, id: string): QueryKey[] {
  const own = keys.agentSessions.one(id);
  if (entity !== "agent_session") return [own];
  const children = queryClient
    .getQueryCache()
    .findAll({ queryKey: keys.agentSessions.all })
    .filter((query) => query.queryKey[2] === "children" && query.queryKey[1] !== id)
    .filter((query) => action === "created" || holds(query.state.data, id))
    .map((query) => query.queryKey);
  return [own, keys.agentSessions.lists, ...children];
}

function targetsOf(queryClient: QueryClient, kind: string, id: string): readonly QueryKey[] {
  const entity = entityOf(kind);
  if (OF_A_SESSION.has(entity)) return sessionTargets(queryClient, entity, kind.split(".")[2] ?? "", id);
  return CARRIED_BY[entity] ?? [[entity]];
}

// Every entity the server pushes on the channel. The router test holds it to
// the kinds the service sends.
export const PUSHED_ENTITIES = [
  "api_key",
  "auth_session",
  "file",
  "invitation",
  "membership",
  "orchestration",
  "user",
  // A copy adds its entries below this line.
  "agent_session",
  "command",
  "control",
  "stream",
] as const;

const KEPT_FRESH = new Set(
  PUSHED_ENTITIES.flatMap((entity) => (OF_A_SESSION.has(entity) ? [keys.agentSessions.all] : (CARRIED_BY[entity] ?? [[entity]])).map((key) => key[0])),
);

/** Whether a push reaches the query under this key: its first element is a
 * pushed entity, or a key the table above names. While the socket is open
 * such a query is as fresh as the last push, so it is not read again on its
 * own (`queryClient.ts`). A query no push names (the person's identity) is
 * not. */
export function isKeptFresh(queryKey: QueryKey): boolean {
  return KEPT_FRESH.has(queryKey[0] as string);
}

/** Whether invalidating `prefix` reads the query under `key` again: a key
 * matches every query whose key starts with it. */
function covers(prefix: QueryKey, key: QueryKey): boolean {
  return prefix.length <= key.length && prefix.every((part, index) => Object.is(part, key[index]));
}

/** Each key once, and none another key already covers. */
function once(targets: readonly QueryKey[]): QueryKey[] {
  return targets.filter(
    (key, at) => !targets.some((other, by) => by !== at && covers(other, key) && (by < at || !covers(key, other))),
  );
}

/** Routes one envelope, live or read back from the stream. */
export function routeEnvelope(
  queryClient: QueryClient,
  envelope: Envelope,
  readers: HintReaders = {},
): RouteOutcome {
  return routeEnvelopes(queryClient, [envelope], readers);
}

/** Routes envelopes handed over together: a push, or what a page read back
 * from the stream keeps. The entity's reader reads the one record each names,
 * or, for an entity with none, every query the entity is read from is read
 * again, once however many of them reach it: each invalidation cancels and
 * restarts a refetch in flight. */
export function routeEnvelopes(
  queryClient: QueryClient,
  envelopes: readonly Envelope[],
  readers: HintReaders = {},
): RouteOutcome {
  const targets: QueryKey[] = [];
  let hinted: string | undefined;
  for (const envelope of envelopes) {
    if (!isEntityChanged(envelope)) continue;
    const entity = entityOf(envelope.payload.kind);
    const reader = readers[entity];
    if (reader) {
      reader.hint(envelope.payload.target_id, envelope.payload.version);
      hinted = entity;
      continue;
    }
    targets.push(...targetsOf(queryClient, envelope.payload.kind, envelope.payload.target_id));
  }
  const invalidated = once(targets);
  for (const queryKey of invalidated) void queryClient.invalidateQueries({ queryKey });
  return hinted === undefined ? { invalidated } : { invalidated, hinted };
}

/** What a page read back from the stream keeps one push of, the last: the
 * record, for an entity whose reader reads each record and for a push that
 * names a session, which reaches that session's reads alone; the entity for
 * any other, since one invalidation reads all of it again. */
export function replayKey(envelope: ChangeEventEnvelope, readers: HintReaders = {}): string {
  const entity = entityOf(envelope.payload.kind);
  return readers[entity] || OF_A_SESSION.has(entity) ? `${entity}/${envelope.payload.target_id}` : entity;
}
