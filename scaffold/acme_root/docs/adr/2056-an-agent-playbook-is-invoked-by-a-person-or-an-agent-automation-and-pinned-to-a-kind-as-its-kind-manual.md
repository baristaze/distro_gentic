# ADR 2056: An agent playbook is invoked by a person or an agent automation, and pinned to a kind as its kind manual

**Status**: accepted (2026-10-11)

## Context

A person publishes an agent playbook, and nothing brought one into a
session: the manager could invoke one, and only tests called it. A
tenant also had no place for its operation kind manual, the standing
instructions every session of a kind should hold. An invoked brief is a
message. After the first summary it sits in the pinned zone, whole
within 8,000 characters and cut to an excerpt beyond, so a kind manual
sent that way would be cut. The engine gives a session standing text:
pinned through the inbox when the session is made, whole in the system
layer of every request, cached with the kind's prompts, and changed only
by a recorded switch.

## Decision

**A person invokes an agent playbook through the API, the command line,
and the session's page.** `POST /v1/agent-playbooks/{name}/invocations`
names the session. The rules hold as they were: a person in person who
may instruct the session, the name's latest version, its gates written
first, and its brief as their message. The CLI's `agent_playbook invoke`
and the portal's session header call the route.

**An agent automation invokes one through its start.** A start action
may name an agent playbook. The person who saves the agent automation
chooses it, as they write its brief, and a name with no version is
refused then. At a firing, the latest version is read before the session
starts, so a name with none refuses the run with nothing made. It is
invoked after the session's budget and before its event and brief, under
the context the agent automation runs as (`invoke_version`). Only an
agent automation's action calls that method, and no tool holds it.

**A tenant pins an agent playbook to a kind as its kind manual.** It is
the same noun, pinned instead of invoked. A pin names a kind, and
optionally one agent project, where it wins over the tenant's. It names
one version, the latest when it is pinned: a later publish moves nothing
until a person pins again, so a kind manual never changes without a
person's act, and its size is checked once. Only a person in person who
manages the tenant pins. A kind no session can start on, an agent
project the tenant does not hold, a name with no version, and a brief
past the standing text's bound, as a session receives it, are refused
with nothing pinned.

**A new session pins its kind manual as its standing text.** The agent
playbooks layer wraps the agents manager, through the root's new
`agents_layer`, so every way a session is made takes it: a start, a
start in an agent project, an agent automation's start, a sub-agent's
spawn, and a hand-over. The agent project is the session's own for a
start, and its origin's for a spawn or a hand-over. The version is
recorded as the session's invocation, marked pinned, before the engine
makes the session, so its gates hold from the first call. A retry of the
make pins the version it recorded, also when the first stopped after the
session's row: the layer sends that version's text again, and the
engine's standing step lands once. A session that stands with none
recorded is passed through untouched. So one made before a pin, or a
re-pin, keeps the kind manual it was made with. A standing text the
maker sends follows the kind manual, the two held to one bound.

**A kind manual's gates are an invoked agent playbook's.** They join the
session's gates through its invocation, so they hold in its sub-agents
too, and they only narrow: a gate never allows, and the text grants
nothing. An invocation of the kind manual's own version sends no second
brief. The lever reading counts a kind manual as a lever the session
reached, since it reads the session's invocations.

## Consequences

- One migration: the table `core.agent_playbook_pins`, one row a kind
  and an agent project, the tenant's row among them, and a `pinned`
  column on `core.agent_playbook_invocations`, false for every row
  before and for every row the release before writes through a roll.
- `build_managers` takes `agents_layer`. The API, the session runner,
  and the maintenance worker each pass the agent playbooks layer's,
  since each makes sessions. A root without it makes sessions with no
  kind manual.
- A kind manual rides every request of its sessions, inside the bound
  that keeps the work in view. Nothing moves a running session to a new
  kind manual: ending it, or switching its standing text, is a person's
  act.
- A pin names an agent project by its id. An agent project removed with
  a pin on it leaves the pin behind, and no session ever starts there to
  read it.
