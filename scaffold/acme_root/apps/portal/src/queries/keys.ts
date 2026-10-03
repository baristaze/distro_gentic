// One key factory per domain. The first element is the entity name the
// server uses in its `entity_changed` pushes, so the realtime router can
// invalidate by convention; an entity the convention does not reach on its
// own (a membership, read through `me`; a user, read through `me` as well as
// its own list) is named in the router's table instead.
export const keys = {
  me: ["me"] as const,
  // The person behind the session: their address and their time zone.
  identity: ["identity"] as const,
  // The person's places across orgs, read with the session under the
  // identity stage. A switch drops it with every other key.
  myMemberships: {
    all: ["my_membership"] as const,
    list: (limit: number) => ["my_membership", "list", limit] as const,
  },
  // The org's memberships: the role beside each member in Settings. A
  // `tenancy.membership.*` push reaches it through the router's table.
  memberships: {
    all: ["membership"] as const,
    list: (limit: number) => ["membership", "list", limit] as const,
  },
  users: {
    all: ["user"] as const,
    list: (limit: number) => ["user", "list", limit] as const,
  },
  apiKeys: {
    all: ["api_key"] as const,
    list: (limit: number) => ["api_key", "list", limit] as const,
  },
  // The org's files. A `media.file.*` push refreshes the usage, since the
  // entity is `file`.
  files: {
    all: ["file"] as const,
    usage: ["file", "usage"] as const,
  },
  // A `tenancy.invitation.*` push invalidates these by convention.
  invitations: {
    all: ["invitation"] as const,
    list: (limit: number) => ["invitation", "list", limit] as const,
  },
  // The tenant's projects, which a new session starts in. No push names a
  // project, so the list is read on its own clock.
  projects: {
    all: ["project"] as const,
    list: (limit: number) => ["project", "list", limit] as const,
  },
  // A tenant's agent sessions and every read of one. A push that names a
  // session (its record, its stream, a hand-over) reaches that session's
  // reads under `one(id)` and, for its record, the lists (the router).
  agentSessions: {
    all: ["agent_session"] as const,
    lists: ["agent_session", "list"] as const,
    list: (status: string, limit: number) => ["agent_session", "list", status, limit] as const,
    one: (id: string) => ["agent_session", id] as const,
    read: (id: string, part: string) => ["agent_session", id, part] as const,
    command: (id: string, key: string) => ["agent_session", id, "command", key] as const,
  },
};
