# ADR 2043: The platform's kinds start sub-agents, each under a share the tree's budget bounds

**Status**: accepted (2026-10-05)

## Context

The engine starts a sub-agent through `spawn_sub_agent` and parks its
parent on its children through `wait_for_sub_agents` ([ADR
1019](1019-a-kind-starts-sub-agents-through-a-tool-and-a-report-clears-its-parents-wait.md)).
A kind that names no tree roots one three levels deep that holds ten
sub-agents besides its root. A spawn refuses a kind that names no share.
A share is a budget on the child's own session, written at the spawn,
so one child cannot spend all its tree has left. The tree's budget, the
root's, bounds every call of the tree, and a share never raises it.

Every kind the platform ships declared a tree of one, and only the
engineer named a share, so that a product's kind could spawn it. No
platform session could split its work. Three things are open: which
kinds start sub-agents, which kinds a sub-agent may run as, and how much
each may spend.

## Decision

**Every kind roots the engine's tree.** No platform kind names a tree,
at any version, so each roots one three levels deep with ten
sub-agents. A tree is read once, when its root starts, and a root starts
at its kind's latest version. So the change reaches new trees only, and
a tree already started keeps its bounds. The planner and the assistant
hand work on and name no spawn tool, so their trees stay empty.

**The engineer and analysis start sub-agents.** Both name the engine's
two tools, and their policy runs a spawn unattended. That is safe
because a child's calls are still decided under its own kind and under
every kind above it, and the strictest decision holds. A prompt layer
says when to split: questions that do not depend on each other, each
worth a session of its own. It also says that a sub-agent works on a
fresh checkout of the default branch, without its parent's changes, so
its objective carries what it needs. Each change is a new version, and
the version before it stays shipped while a session may run it.

**A sub-agent runs as the engineer or as analysis, each under its
share.** A spawn names one of the two, or takes its caller's. Both
shares are reference cost at list price: the loops a share pays for, at
the kind's step guard, over a cached window at 0.10 a call.

| Kind | Share | Why |
|---|---|---|
| Engineer | 60 | Three loops at its step guard of 200: its change, and two follow-ups |
| Analysis | 10 | Two loops at the engine's step guard of 50: it reads and answers, and one follow-up |

Each share is more than one worst-case call of the main role at a full
window: about 2.82 for its fill (a million prompt tokens written to the
cache at 2.50 per million, and 32,000 output tokens at 10) and 5.73 for
its fallback. So a share never refuses a child's first call. The planner
and the assistant name none: a person starts them, and a spawn refuses
them.

**The tree's budget bounds them all.** A share bounds one child. The
tree's budget, when the root has one, such as an automation's run cap,
bounds the whole tree, whatever its shares add up to. A share below the
tree's budget lets several children run before the tree refuses the
next call. With no budget on the tree, its sub-agents can spend at most
ten times the largest share, 600, besides what the root spends, and
every call still passes whatever budget its person, its project, and its
tenant hold. Shares do not nest: a child's calls are charged to its own
session, the tree, its person, its project, and the tenant, never to its
parent's session. So a parent's share never pays for its children.

## Consequences

- An engineer or analysis session can start up to ten sub-agents, three
  levels deep, and wait on them. It wakes on each report.
- A session that splits its work spends more: each child up to its
  share, the tree up to its budget.
- A tree with no budget of its own can spend up to 600 through its
  sub-agents. A tenant that wants less sets a budget on the person, the
  project, or the tenant, or a run cap on the automation that starts it.
- A session on the engineer's version 4 or analysis's version 2 keeps
  its tools and starts no sub-agent.
- A product's kind may now spawn analysis too, under its share.
