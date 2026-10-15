# ADR 2063: The platform's nouns name the agent, and a rename leaves nothing behind

**Status**: accepted (2026-10-14)

## Context

A scaffold is copied into a product. The platform's nouns and the
product's then share one codebase, one database, one API, and one
portal. Several of the platform's nouns are bare words a product needs
for itself: a project, billing, an automation, knowledge, a playbook, a
notification, a fleet, a relay, a delivery, an arm, an environment. A
robotics program, a SaaS's own billing, a CRM's automations, a
helpdesk's knowledge base, and a robot fleet each mean something else by
them. The platform's own tables, modules, and routes that carry the
engine's nouns (a session, a workspace, a machine) collide the same way.

## Decision

**A noun of the platform's names the agent or the mechanism it serves.**
A project is an agent project, an automation an agent automation,
knowledge agent knowledge, and a playbook an agent playbook. Billing is
agent billing, with its spend account, unit plan, spend unit, and spend
ledger, and an account link is an identity link. A notification is a
park alert, the fleet the agent fleet, the relay the exec relay, a
delivery the work product, and an arm a contender. The kinds `engineer`
and `operator` are `software_engineer` and `ops_analyst`. A project's
environment is its workspace base, a run's is its run image, and a
check's is its executor. The platform's session and workspace tables
take the agent's name, and the cloud pool's machines are its VMs.

**A rename is hard.** Every surface moves at once: the namespace, the
class, the table, the column, the route, the CLI, the portal's route and
label, the event kind, the stored value, the model-visible tool, the
skill, the lens, and the spec's prose. No alias, shim, duplicate, or
deprecated route is left. A route moves inside `/v1`, which departs
from the guideline's rule that a removal is a new prefix: no copy runs
in production, so the path moves in place, and the changelog names the
move as breaking.

**Rows stay, and stored values move with them.** A table moves by a
migration that renames it, never one that drops and creates it. In the
same migration, every stored value that names the old noun moves in
place: an event kind, a pinned tool name, a kind id, an enum value, and
a key inside a stored document or a held work item. Each downgrade
restores both.

**A kind version's bytes change in place.** A shipped kind's tool names
and texts carry the renamed nouns, so its rendered bytes change and its
pinned digest is re-pinned. Its version stays: the old names cannot be
kept, so no version could hold them.

**What another layer owns stays as that layer names it.** The engine's
budget scope value is `agent_project`, its workspace providers are its
agent workspaces', and its machines its VMs. A run's results stream keeps its
`environment` key, which a product's runner writes under schema 1. The
lens group `workspaces` and its two skills keep their names.

## Consequences

- A rollback across this release is not supported. The release before
  reads the names this release renames, so its integration tests that
  read them are left out of the release-before run
  (`scripts/release_before_deselect.txt`).
- A secret's value is kept in its tenant's store under its owner kind,
  its owner, and its name. No migration reaches the store, so a value an
  agent project declared before this release stays under the old owner
  kind. Its owner puts it again after the upgrade; a downgrade reads the
  old one again.
- A host's ceilings file names `agent_projects`.
- The change stream keeps each past event's payload as it was written.
  Only its kind moves.
- A lens group's id may carry a hyphen, as `agent-fleet` does.
- An agent project's workspace base is `AgentProjectWorkspaceBase`,
  apart from the engine's `AgentWorkspaceBase`.
