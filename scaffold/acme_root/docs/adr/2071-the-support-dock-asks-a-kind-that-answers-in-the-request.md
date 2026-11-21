# ADR 2071: The support dock asks a kind that answers in the request

**Status**: accepted (2026-11-21)

## Context

The portal's support dock answers questions from the tenant's own
records ([ADR 2045](2045-the-support-dock-continues-a-conversation-only-when-it-is-the-persons-own.md)).
It needs no workspace and no worker. Its answers came from a session of
the platform assistant, so a queue hop and a runner's claim stood before
the first word, and that is the wait a person sees.

ADR 1044, "A kind's loop may run in the request that asks it", lets a
kind's loop run in the request instead, when the kind holds no worker's
work: no workspace, no sub-agent, no job, no call that waits for a
person, within 10 model calls and 30 seconds. The platform assistant
hands engineering work to a software engineer in a session of its own,
so it cannot be such a kind.

The API already runs such a loop through the trust wall, its audit, the
agent playbook gates, and the knowledge recall. It did not take what a
worker's loop takes: the model matrix's fills and a tenant's own keys,
the agent knowledge and agent automation readers, the connectors'
toolsets, and the agent automation principal. And the platform read
`GET /v1/agent-sessions/{id}/questions` as what a session waits on a
person for, beside `POST` on the same path, which asks a request kind.

## Decision

**The dock asks a kind of its own.** The support assistant
(`support_assistant`) reads and drafts what the platform assistant does:
the corpus, the agent knowledge, the tenant's records, the tool policy
draft, and a product's readers and its section of the object model. It
hands no work on, holds no workspace, and keeps to the request's bounds.
Its loop runs in the request that asks it. The platform assistant stays
as it is, for sessions. Every other kind the platform ships runs in a
worker: each holds a workspace, a sub-agent, a hand-off, or bounds past a
request's.

**The dock shows the answer as it streams.** A question starts the
person's conversation or continues it through the question route. The
portal's client reads the server-sent events, and the dock shows the
text as it comes, then reads the history once the stream ends. An answer
that stopped where a loop would park says its cause, and the next
question runs. One question runs at a time. Each question still carries
the page as data, and the dock still continues only the person's own
conversation, now one of the support assistant's.

**No worker touches a request kind's session.** The runner completes a
loop item that names one without a run, and the stalled sweep passes one
over: its next question takes it up. An agent automation that would
start a request kind is refused when it is saved, since a firing asks no
question. A connector is never attached to one, since its calls outlast
a request and most wait for a person. So no loop hook attaches a toolset
to a request kind, and its session runs as its person, never as the
agent automation principal.

**The API's loop takes what a worker's takes.** The model matrix resolves
its fills, and a tenant on its own keys calls on them through trust. The
agent knowledge and agent automation readers read there, as the runner's
do.

**A question's session stands in no agent project.** What the dock
answers is the tenant's, read on the person's own permissions, so it
names none. The tenant's own policies hold the session: its budgets, its
retention, its agent knowledge. The rule that a start outside a local
stack names an agent project does not reach a question.

**What a session waits on a person to unlock is read at `/unlocks`.**
`GET /v1/agent-sessions/{id}/unlocks` answers it, and `POST
/v1/agent-sessions/{id}/questions` asks a request kind. The path moves
in place, inside `/v1`, as ADR 2063 moves a route.

## Consequences

- The dock's first word waits for no queue and no claim.
- A support conversation's own page takes no message: its composer
  points to the dock, since a message there reaches no worker.
- A conversation the dock kept of the platform assistant's kind is no
  longer continued: the next question starts one of the support
  assistant's, and the earlier one stays a session.
- A product's reader joins both assistants. One a request may not hold
  refuses the platform at start, naming the breach.
- An agent project's budget does not hold a dock question; the tenant's
  does. A question that names an agent project is worth adding when a
  tenant asks to cap support by project.
- A request that dies mid-loop leaves its session pending, and nothing
  wakes it until its person asks again.
- A local or staging stack that ships the platform's agents offers the
  support assistant in place of the example assistant of ADR 1044, whose
  read tool shares a name with the platform's own.
