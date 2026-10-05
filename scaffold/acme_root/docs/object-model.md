# The object model

What each thing in Acme is, what owns it, the states it moves through,
and what moves it between them. It is written for the people who run
their part of the platform, and the platform assistant explains from it.
Each section names the assistant's reader that shows the thing live. A
reader shows only what the asking person may read.

## The org and its people

The **org** owns everything below. A person holds one **role** in it,
and the role decides what they may do:

| Role | May |
| --- | --- |
| `owner` | everything, including deleting the org |
| `admin` | read, write, manage people and budgets, manage API keys |
| `member` | read, write, manage API keys |
| `viewer` | read |

Writing covers starting a session, writing to one, and every control on
it. Nothing of one org is ever visible from another.

## Projects

A **project** belongs to the org and is bound to one repository, where
its sessions' work lands. A session belongs to at most one project,
named before the session exists, and it never moves. A project has no
states: it is there until an admin removes it.

Readers: `list_projects`, `read_project`.

## Agent sessions

An **agent session** belongs to the org. A person starts it, an
automation starts it, another session hands work to it, or a session
spawns it as a **sub-agent**, a child in its tree. Its **kind** fixes
its tools when it starts. It is a series of **loops** over one history,
and it never ends.

| State | Means | Moves on when |
| --- | --- | --- |
| `idle` | no loop is open | a message or an event wakes it: `pending` |
| `pending` | a loop waits on the work queue | a runner claims it: `running` |
| `running` | a runner holds its loop | the loop waits: `parked`; it ends: `idle` |
| `parked` | its loop waits on something | that clears: `pending` |

A loop ends as `succeeded`, `failed`, `inconclusive`, `cancelled`, or
`errored`. A park is none of these: the loop goes on once it clears.
Any person who may write can cancel a session from its page. A session
marked **archived** wakes for nothing; one marked **deleted** is hidden
from every read until it is restored.

Readers: `list_sessions` (by status, park reason, or project, newest
first), `read_session` (where one stands and what its park waits on),
`read_wait` (its place in the queue and its hosts).

## Why a session is parked

Every park names its reason. This table holds every reason the engine
has.

| Reason | It waits on | What clears it | Who may clear it | Reader |
| --- | --- | --- | --- | --- |
| `person` | a call held for approval, a question, or a call far above the session's norm | a decision on the call, or an answer as a message | a held call: the roles the tool policy lets decide its class, the owner and admins unless the policy names others; a question: the person who asked for the work, or an admin when they have left; a call above its norm: an admin or the owner | `read_session` names each held call and who decides it |
| `provider` | a model provider's outage, rate limit, or billing or credential error | the provider answers again; the session retries at its own time | nobody: it retries by itself; a tenant's own key that fails needs an admin to fix it | `read_session` gives the retry time |
| `budget` | the budget gate refused the next call | the budget is raised or resets, or the account is topped up | an admin or the owner, who set budgets | `read_session` names the budget in what clears it |
| `resource` | a workspace no host can give yet, or a scarce resource in line | the host comes back, or the resource frees; the session asks again at its retry time | when the one host that holds its workspace is offline: whoever runs that machine brings it back; an admin or the owner can revoke it, and another host of the pool prepares a new workspace without the old one's files; a person who may write can move the session to the cloud or another pool. Otherwise nobody: it takes its turn | `read_session` gives the retry time; `read_wait` names the host that holds the workspace, whether it is online, and since when |
| `job` | a long-running job a tool started | the job reports, or its deadline passes | nobody | `read_session` |
| `children` | sub-agents that have not reported | each child reports | nobody; a person who may write can cancel a child | `read_session` lists the children |
| `handover` | a person working in the session's environment by hand | that person gives it back | the person who took it over | `read_session` |
| `pause` | a person paused it | a person resumes it | any person who may write | `read_session` |

A session waits without a park too. A `pending` session waits on the
work queue, and a session pinned to the org's own hosts waits for one of
them to be online, or for the one that holds its workspace: see the next
section.

## The work queue and the hosts

A pending session's loop is an **item** on the work queue, in the
**lane** where what it needs runs. The org's **fair share** says how
many of its loops run at once: a loop over it waits its turn and never
fails. A slow start is most often loops of the same org running ahead
of it.

A **host pool** is a set of the org's own machines, inside its wall. A
**host** joins a pool with an enrollment token an admin issued, and it
is online while it calls in. A session **placed** in a pool runs there;
with no host online it waits, and it never moves to the cloud unless a
person moves it. A **workspace** lives on the host that prepared it, so
the session runs there: while that host is offline, the session waits
for it, even with other hosts of the pool online.

Reader: `read_wait` (the loop's item: queued or running, its lane, since
when, its attempts, and the org's loops running ahead of it; where the
session runs, which of the pool's hosts are online, and the host that
holds its workspace, whether it is online, and since when).

## Tools and who agrees to them

A **tool** is one thing an agent can do. Each declares its **class**:
`read`, `write`, `execute`, `integration`, and the others a policy
names. The org's **tool policy** says, by class and by target, which
calls run on their own, which wait for a person, and which never run,
and which roles may approve each class. A call that waits is **held**:
its session parks on `person` until someone who may decide it approves
or denies it, from the session's page. A decision is a step of the
session's history.

The assistant drafts a change to the policy and shows its difference
from what is live. An admin applies it.

## Budgets

A **budget** says how much may be spent: by a session, a tree of
sessions, a person, a project, a team, or the whole org, over its life
or per period. Every model call asks the **gate** first. When the gate
refuses, the session parks on `budget` until the budget is raised or
resets.

## Automations

An **automation** belongs to the org. A person creates it, and it runs
as its creator or as the org's automation principal. An event or a
schedule **fires** it, and every firing is a recorded **run**:

| Run status | Means |
| --- | --- |
| `started` | its action ran: it started a session or wrote to one |
| `queued` | a limit stopped it, and it waits its turn |
| `refused` | it never runs, and its refusal says why |

A run is refused for its own session's event (`own_event`), a chain past
its hop limit (`hop_limit`), its cost cap (`cost_cap`), its rate
(`rate`), its concurrency (`concurrency`), a full queue (`queue_full`),
a creator who left or a principal not granted (`principal`), an action
that cannot run (`action`), a start with no project where one is needed
(`project`), or the platform's own act with no session recorded for it
(`unattributed`). A person who may write changes its limits or turns it
off, in person; one that runs as its creator, only its creator.

Readers: `list_automations`, `read_automation` (its trigger, its action,
its limits, and its recent runs, newest first).

## Knowledge

The org's **knowledge** is what its people keep for later sessions: an
entry for one project or the whole org. An agent may suggest one, and
no session reads it until a person reviews it. The platform's own
documentation, this page among it, is knowledge too.

Readers: `search_knowledge`, `read_knowledge`, `search_corpus`.

## Validation sessions

A **validation session** runs one check of a project's policy at a
delivered commit, on a fresh machine, with no agent. It is `queued`
while its work waits or runs, then `finished` with the run it recorded,
or `refused` with the reason the check cannot run here.

## The product's own

A product built on Acme adds its own section below this one: each of its
entities, what owns it, its states and what moves it, every state that
waits and what clears it, and the reader that shows it.
