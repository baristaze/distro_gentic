# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.6.0 (2026-10-05)

The portal becomes a three-pane, session-first app: a left bar of
sessions, the session's story as a live chat, and its evidence as tabs
beside it, with set-up-once screens in Settings. Sessions start
sub-agents three levels deep and show them live. A support dock answers
beside any page from the tenant's own records. The platform builds on
the engine at v0.6.1. Minor: routes move into Settings (each old
address lands on its new one), the portal gains a slot a product fills,
`StepView` gains fields, the platform assistant moves to version 2, and
the platform's kinds start sub-agents. A copy that kept entries in
`DROPPED_TABLE_ROLES` drops them.

### Added

- The portal's shell: a left bar of sessions grouped into Needs you,
  Running, and Recent, a sub-agent nested and folded under its parent; a
  Home that is one composer with starter prompts; ⌘K across sessions,
  settings, and actions; and a slot (`src/product.tsx`) where a product
  adds its pages, left-bar entries, session tabs, tools' cards,
  settings, agents, and examples, refused at start when it shadows a
  platform address. ADR 2042 (#95).
- Settings, in its own bar: Personal, Organization, Agents, and
  Security, each section a screen that was a page before, and every
  field with a realistic example as its placeholder (#96).
- A session reads as a live chat: thoughts, work blocks of one-line
  calls, and cards for an action to decide, a question, a plan, a pull
  request, a validation, and a result; text streams as it is written,
  and Send works at any time, with Pause beside it. `StepView` carries a
  model's `thinking` and `tool_uses` and a tool step's `tool_use_id`,
  each empty where the content is sealed or gone (#97).
- A session's right pane holds its evidence as tabs (Workspace with take
  control, Step, Changes, Evidence, Plan, Sub-agents, Usage) that a
  product can add to; it opens itself once a session and keeps its tabs
  and width (#99).
- A session's sub-agents read live: one card for the sub-agents an
  answer starts, each row with its activity; report cards that link a
  child and its parent; a park line naming each child's state; a status
  line that names the running call, or "Needs you in a sub-agent" from
  any depth; an outline of the timeline; and a toast on any page when a
  session starts to need its person. `StepView` names the agent that
  wrote a message (`agent`) (#100).
- The platform assistant, at version 2, reads the tenant's sessions,
  projects, automations with their runs, and what a waiting session
  waits on, each under the asking person's context;
  `ProductKinds.assistant_tools` adds a product's readers; and
  `docs/object-model.md` gives each entity, park reason, and unlock with
  who may clear it (#101).
- A support dock beside any page: "?", `⌘/`, or "Ask support" opens it;
  the session's pane folds to its rail beside it, and under 1100px it is
  a sheet. A reply's link becomes a chip only when the router matches
  it, and opens its page in the main area. A person keeps one standing
  support conversation, out of the work lists. `docs/portal-routes.md`
  lists every route for the assistant. ADR 2045 (#103).
- The platform's kinds start sub-agents: every kind roots the engine's
  tree (three levels, ten sub-agents); engineer v5 and analysis v3 call
  `spawn_sub_agent` and `wait_for_sub_agents`, analysis for a question
  that only reads, each under its share. ADR 2043 (#104).

### Changed

- The base moves to agentic_core v0.6.0 and then v0.6.1: the sub-agent
  tools, a sub-agent's call decided under the kind and the playbook
  gates of every session above it (a deleted one's included), a session
  with a sub-agent at work below it never deleted, and a cancel that
  reaches past a deleted sub-agent (#102, #106).
- The role check reads the tables a chain dropped off the chain itself,
  and the platform's text holds no product's nouns (#98).

### Fixed

- An automation's run stays open while any session of its tree still
  works, so its concurrency counts a tree whose sub-agents run (#105).
- The retention sweep marks a session whose sub-agent waits below it:
  it cancels the parked loops of the tree, each cancel coming down as a
  parent's, and the next pass marks the session; a sub-agent's report to
  a parent whose key is revoked is dropped, and its loop ends (#107).

### Removed

- `DROPPED_TABLE_ROLES`: the chain already says which tables it dropped
  (#98).
