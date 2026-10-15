// One key factory per domain. The first element is the entity name the
// server uses in its `entity_changed` pushes, so the realtime router can
// invalidate by convention; an entity the convention does not reach on its
// own (a membership, read through `me`; a user, read through `me` as well as
// its own list) is named in the router's table instead.
export const keys = {
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
  // The session's flags, one snapshot. No push names them, so they are read
  // again on focus and on an interval (flags.ts).
  flags: ["flags"] as const,
  // The person behind the session: their address and their time zone.
  identity: ["identity"] as const,
  // A `tenancy.invitation.*` push invalidates these by convention.
  invitations: {
    all: ["invitation"] as const,
    list: (limit: number) => ["invitation", "list", limit] as const,
  },
  me: ["me"] as const,
  // The org's memberships: the role beside each member in Settings. A
  // `tenancy.membership.*` push reaches it through the router's table.
  memberships: {
    all: ["membership"] as const,
    list: (limit: number) => ["membership", "list", limit] as const,
  },
  // The person's places across orgs, read with the session under the
  // identity stage. A switch drops it with every other key.
  myMemberships: {
    all: ["my_membership"] as const,
    list: (limit: number) => ["my_membership", "list", limit] as const,
  },
  users: {
    all: ["user"] as const,
    list: (limit: number) => ["user", "list", limit] as const,
    one: (id: string) => ["user", "one", id] as const,
  },
  // A copy adds its entries below this line.
  // The tenant's agent projects, which a new session starts in. No push names an
  // agent project, so the list is read on its own clock.
  agentProjects: {
    all: ["agent_project"] as const,
    list: (limit: number) => ["agent_project", "list", limit] as const,
    one: (id: string) => ["agent_project", id] as const,
  },
  // The records below are named by no push, so each is read on its own
  // clock and again after a write of the screen's own.
  // The tenant's own provider keys: records only, never a value.
  providerKeys: {
    all: ["provider_key"] as const,
    list: (limit: number) => ["provider_key", "list", limit] as const,
  },
  // The tenant's part of the model matrix: what it may choose, and what it chose.
  matrix: {
    all: ["fill_choice"] as const,
    options: ["fill_choice", "options"] as const,
    choices: ["fill_choice", "list"] as const,
  },
  agentAutomations: {
    all: ["agent_automation"] as const,
    list: (limit: number) => ["agent_automation", "list", limit] as const,
    one: (id: string) => ["agent_automation", id] as const,
    principal: ["agent_automation", "principal"] as const,
  },
  // An agent playbook is read by its name, at its latest version.
  agentPlaybooks: {
    all: ["agent_playbook"] as const,
    one: (name: string) => ["agent_playbook", name] as const,
  },
  agentKnowledge: {
    all: ["agent_knowledge"] as const,
    list: (status: string, limit: number) => ["agent_knowledge", "list", status, limit] as const,
    one: (id: string) => ["agent_knowledge", id] as const,
  },
  // The org's events, newest first, as the audit reads them.
  audit: {
    all: ["audit"] as const,
    list: (limit: number) => ["audit", "list", limit] as const,
  },
  // Each budget with what its current window holds and spent.
  usage: {
    all: ["usage"] as const,
    list: (limit: number) => ["usage", "list", limit] as const,
  },
  // A tenant's agent sessions and every read of one. A push that names a
  // session (its record, its stream, a hand-over) reaches that session's
  // reads under `one(id)` and, for its record, the lists (the router).
  agentSessions: {
    all: ["agent_session"] as const,
    lists: ["agent_session", "list"] as const,
    list: (among: string, status: string, limit: number) => ["agent_session", "list", among, status, limit] as const,
    one: (id: string) => ["agent_session", id] as const,
    read: (id: string, part: string) => ["agent_session", id, part] as const,
    command: (id: string, key: string) => ["agent_session", id, "command", key] as const,
  },
};
