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
| `person` | a person: a held call, a question, a call far above the session's norm, a principal who left, nobody to pay, a step guard, a deadline, or a lost workspace | what its unlock says: see the next section | what its unlock says: see the next section | `read_session` names the unlock, and each held call with who decides it |
| `provider` | a model provider's outage, rate limit, or billing or credential error | with a retry time, the provider answers again and the session retries by itself; without one, a key or the provider's account is fixed, then the park is unlocked | with a retry time, nobody; without one, see the next section | `read_session` gives the retry time and the unlock |
| `budget` | the budget gate refused the next call | the budget's window resets or its held calls settle, the budget is raised, the account is topped up, or the call is priced | an admin or the owner raises a budget; whoever pays tops up the account; only the platform's operator prices a call | `read_session` names the budget in the unlock |
| `resource` | a workspace no host can give yet, or a scarce resource in line | the host comes back, or the resource frees; the session asks again at its retry time | nobody: it takes its turn; for an offline host that holds its workspace, see the next section | `read_session` gives the retry time; `read_wait` names the host that holds the workspace, whether it is online, and since when |
| `job` | a long-running job a tool started | the job reports, or its deadline passes | nobody | `read_session` |
| `children` | sub-agents that have not reported | each child reports | nobody; a person who may write can cancel a child | `read_session` lists the children |
| `handover` | a person working in the session's environment by hand | that person gives it back | the person who took it over | `read_session` |
| `pause` | a person paused it | a person resumes it | any person who may write | `read_session` |

A session waits without a park too. A `pending` session waits on the
work queue, and a session pinned to the org's own hosts waits for one of
them to be online, or for the one that holds its workspace: see "The
work queue and the hosts".

## What each park waits on

A park names its **unlock** beside its reason: exactly what it waits
on. `read_session` gives it. This table holds every unlock the engine
writes. Any person who may write can **unlock** a park, or cancel the
session, from the session's page. An unlock makes the session check
again: where the cause is still there, it parks again.

| Unlock | Reason | Its cause | What clears it | Who may clear it | Reader |
| --- | --- | --- | --- | --- | --- |
| `approval` | `person` | the tool policy holds a call for a person's decision | an approval or a denial of each held call, on the session's page | the roles the policy lets decide the call's class, in person: the owner and admins unless the policy names others | `read_session` names each held call and who decides it |
| `answer` | `person` | the agent asked its person a question, or stood down and said what it needs | a message from a person, which is the answer | any person who may write; the notice goes to the person who asked for the work, or to the admins and the owner when they have left | `read_session` |
| `principal` | `person` | the person a session runs as left the org or lost their place in it | a person takes the session over: it runs as them from then on, and its sub-agents follow | any person who may write | `read_session` |
| `spender` | `person` | nobody can be named to pay for the next call: no person's message in the session and no payer passed down to it, or the payer's account cannot be read | a person's message gives it a payer, then an unlock; a message alone does not wake it | any person who may write | `read_session` |
| `step_guard` | `person` | the loop made as many model calls as its step guard allows between two looks of a person | an unlock, once a person has looked: the count starts again | any person who may write | `read_session` |
| `deadline` | `person` | the deadline of the session's tree passed | a later deadline, or none, for the whole tree; an unlock alone trips it again | any person who may write | `read_session` |
| `workspace` | `person` | the workspace was lost: the branch it is rebuilt from is gone from its repository, or moved on both sides | the branch is put back in the repository, then an unlock prepares the workspace again; otherwise a cancel | any person who may write | `read_session` |
| `anomaly` | `person` | the next call's expected cost is far above the session's norm, over ten times its median; the operator is told too | an approval of calls up to an amount, which wakes it; an unlock alone parks it again | an admin or the owner | `read_session` |
| `workspace` | `resource` | no host can give the workspace yet: the one host that holds it is offline, no host has prepared it yet, or none can meet the isolation its kind asks | the session asks again each minute, by itself, and runs once a host can give it | for the offline host that holds it: whoever runs that machine brings it back; an admin or the owner can revoke it, and another host of the pool prepares a new workspace without the old one's files; a person who may write can move the session to the cloud or another pool. Otherwise nobody | `read_wait` names the host that holds the workspace, whether it is online, and since when |
| `price` | `budget` | nothing prices the call's cost: the model, or the call, has no price the platform knows | the operator prices it, then an unlock lets the call through | only the platform's operator; no member of the tenant can, and nobody in it is told | `read_session` |
| `own_amount` | `budget` | the call passes the amount its own request set | an unlock, or a cancel | any person who may write | `read_session` |
| a budget's id | `budget` | the budget line that binds longest refused the next call | with a retry time, its held calls settle or its window resets, and the session tries again by itself; else a raise of the budget, which wakes it | an admin or the owner, who set budgets | `read_session` names the budget |
| `held` | `budget` | other calls still running hold the room this call needs | the session tries again within thirty seconds, by itself | nobody | `read_session` |
| `funds` | `budget` | no units left on the account cover the call | with a retry time, the next billing period starts and the session tries again by itself; else a top-up of the account | whoever pays for the account; the notice goes to the admins and the owner | `read_session` |
| `give_back` | `handover` | a person took the session's environment to work in it by hand | that person gives it back, with what they did | the person who took it over | `read_session` |
| `resume` | `pause` | a person paused the session | a resume | any person who may write | `read_session` |
| a job's key | `job` | a long-running job a tool started is working; the retry time is its deadline | the job completes, or its deadline passes and it is cancelled and answered as timed out | nobody; a person who may write can cancel the session | `read_session` |
| a provider's name, such as `anthropic` | `provider` | the provider is failing: an outage, or the retries a call may make are spent | the session tries again at its retry time, by itself | nobody | `read_session` gives the retry time |
| `<provider>:key` | `provider` | the tenant pays its provider itself and holds no live key for it | a key is saved, then an unlock; saving a key does not wake it | an admin or the owner saves the key; any person who may write unlocks | `read_session` |
| `<provider>:billing`, `<provider>:credential`, `<provider>:permission` | `provider` | the provider refused the call: its billing, the key itself, or a permission, region, or model the key cannot reach | the account or the key is fixed at the provider, or a new key is saved, then an unlock | for the tenant's own key, an admin or the owner; for the platform's key, the operator; any person who may write unlocks | `read_session` |

The engine writes no park on `children` today.

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
