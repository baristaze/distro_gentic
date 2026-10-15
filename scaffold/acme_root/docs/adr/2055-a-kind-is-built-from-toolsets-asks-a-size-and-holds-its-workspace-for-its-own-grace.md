# ADR 2055: A kind is built from toolsets, asks a size, and holds its workspace for its own grace

**Status**: accepted (2026-10-11)

## Context

The engine lets a kind name toolsets rather than every tool ([ADR
1031](1031-a-kind-is-built-from-toolsets-and-a-deferred-toolset-loads-as-a-recorded-switch.md)),
and ask a model size and an effort of each model role it calls ([ADR
1032](1032-a-kind-asks-a-model-size-and-an-effort-of-each-model-role.md)).

The platform's kinds still listed their tools one by one, at every
version. The matrix keyed a question on its environment, model role,
agent kind, plan tier, and workload class ([ADR
2012](2012-the-model-matrix-is-the-engines-resolver-and-a-tenants-key-reaches-its-call.md)),
so a role a kind asked a size of took its role's row. A kind declared as
data could say how much model a role needs, and the matrix would not
hear it: a new kind that needs a smaller or a larger model needed a row
of its own.

A workspace no run accounts for was held for one grace per runner,
`ACME_RUNNER_WORKSPACE_GRACE_SECONDS`, 300 seconds, whatever its kind.
The grace exists so a follow-up finds its workspace warm. A follow-up
later than the prompt cache's life writes its cached prefix again
anyway, so a workspace held past that life is paid for and saves little.

## Decision

**The platform's tools form eight toolsets.** Each groups tools a kind
takes whole, by what they let it do. `files` lists, reads, and searches
a workspace. `code` edits and writes its files and runs commands.
`agent_knowledge` searches and reads what the team knows. `work_product`
validates, opens the pull request, and submits the result. `sub_agents`
starts sub-agents and waits for them. `records` holds the assistant's
readers, `handoff` the hand-off to a software engineer, and `tool_outputs`
the read of a result kept outside the window.

**Every shipped kind is rebuilt from them, at every version.** A kind
names alone a tool whose toolset would give it more than it may call.
Analysis runs commands and edits nothing, so it names `run_command`
alone. The software engineer names `suggest_agent_knowledge` alone, the
planner `read_agent_session`, and the assistant its corpus search and its
policy draft. Each version's tools are the same set as before, and the
registry renders by name, so each renders the same tool definitions,
byte for byte, and keeps its version. A kind whose tools change is a new
version.

**A product adds toolsets beside the platform's.** `ProductKinds.toolsets`
declares them. A toolset of its own under one of the platform's names is
refused at boot, and so is a kind of its that names a toolset neither
declares, at its version and with its tools.

**Every shipped kind asks L of its main role and S of its summarizer.**
The engine's default sizes put those on the models the two roles ran
on, so the shipped kinds' models, and their spend, do not move.

**The matrix keys on the model size.** A question carries the size its
kind asks of the role, or none. A row may name a size, and answers only
a question that asks it. The keys' order, which breaks a tie between two
rows that name as many keys, is now environment, size, role, kind, plan
tier, workload.

- A question asks its size only of a version that holds a row that
  names that size. Of a version that holds none, it is asked with no
  size, and resolves as a question that asks none. A version published
  before this holds no such row, so it answers every question as it did;
  one published since holds a row for each size a kind asks, so its
  asks take the order below.
- A question that asks a size of a version that holds a row for it
  takes a row that names its kind first, whatever else either row
  names. An operator's row for a kind is never passed over for a size's
  row, however either is narrowed.
- Then it takes a row that names the size, before every row that names
  neither, as the engine resolves an ask. A new kind that asks a size
  takes its size's row with no edit to the matrix.
- Within each, the row that names more keys wins, then the one that
  names the earlier key. A question that asks no size resolves as it
  did: no row that names a size matches it, and the other keys keep
  their order.
- A row that names a size and no role serves every role the version
  serves, as the row that matches everything does. Each of its fills
  needs a passing benchmark for each of them, and a tenant on its own
  keys may choose one for any of them. An operator who wants it narrower
  names the role too.

**Every asked size has its row.** A version is not published without a
row that names each size a kind it answers asks, the platform's and the
product's, as it is not without each role they call. The seeded version
holds a row for each of the engine's five sizes. An operator's body may
name a row's size, and a fill's efforts, the levels an ask may move it
to; the views show both.

**A kind holds its workspace for its own grace.** Holding a workspace
after a loop is the platform's: the engine releases one at each run's
end. So the grace sits beside the kind, not on the engine's type.
`GRACES` holds the shipped kinds', and `ProductKinds.graces` a product's
own. One that names none takes the default. No grace runs past the
prompt cache's life, five minutes, the shortest a provider the platform
calls keeps a cached prefix: a product's grace past it is refused at
boot. The software engineer and analysis hold theirs for that life, as
long as the runner's setting did. The held-workspace sweep reads the
session's kind's grace once, when a pass first finds its instance
unaccounted for, and the runner's setting is gone.

**Nothing is migrated.** A version's rows are stored as JSON, and a row
stored without a size reads as one that names none.

## Consequences

- A product declares a kind as data: its toolsets, the size it asks of
  each role, and its grace. Its model comes from the size's row, and its
  workspace is held for its grace, with no edit elsewhere.
- Each shipped kind's sessions keep their cached prefix: its tool
  definitions are unchanged.
- The first version an operator publishes after this needs a row for L
  and for S. Until then, the published version answers every question as
  it did: it holds no row that names a size, so no question asks it one,
  and a deploy alone moves no kind to another model.
- In a version with those rows, a row an operator writes for a kind,
  naming no role, answers each role the kind asks a size of before the
  role's row, which it lost to before. A role the kind asks nothing of
  ranks it as it did.
- An idle workspace is held for its kind's grace, never past the cache's
  life. A runner's grace is no longer set per runner.
