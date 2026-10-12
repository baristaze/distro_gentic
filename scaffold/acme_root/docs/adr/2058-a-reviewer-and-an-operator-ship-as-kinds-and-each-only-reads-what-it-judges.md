# ADR 2058: A reviewer and an operator ship as kinds, and each only reads what it judges

**Status**: accepted (2026-10-11)

## Context

The platform shipped four kinds: the engineer, analysis, the planner,
and the assistant. Two more roles are generic to any agentic product:
reviewing a change, and reading how the platform runs. A product that
wanted either wrote it whole.

The forge's integration only wrote. It pushed a branch, opened a pull
request, and posted a comment; nothing read a pull request back.

A workspace checks out its session's own branch, `sessions/<id>`, and
the push token the platform mints for a session writes that branch.

The engine's result tool carries a claim and the ids of what shows it,
and the gate the platform injects judges them. That gate knew one kind
of evidence, the runs of a validation.

The assistant's reach was checked at boot. Nothing held any other kind
to reading alone.

## Decision

**The forge reads a pull request back.** `read_pull_request` answers
its head, the files it changes with their patches, and the checks at its
head; `read_file` answers a file at a commit. Each goes through the
installation its caller names, as a write does, and the caller first
finds that the session's own tenant connected it (`intake.tools.connected`,
which the comment shares). The twin answers a pull request recorded in
it, and the chat and an absent integration refuse.

**The reviewer ships.** It is built from the `review` toolset
(`read_pull_request`, `read_pull_request_file`, `note_finding`,
`submit_review`), `knowledge`, and `artifacts`, and names the forge's
`comment` alone. It asks XL of its main role, since a review is worth
the defects it finds, and S of its summarizer. Its authority is steady,
and it names a share, so a lead may start it as a sub-agent.

**The reviewer has no workspace.** A workspace checks out its session's
own branch. Checking out another session's branch would change how
every session's workspace is prepared, snapshotted, and pushed: a
mechanism every loop passes through. Reading through the forge at the
head reads the same branch and writes nothing. No tool the reviewer
holds writes a file, runs code, or pushes.

**A finding is noted, and the review cites it.** The engine's result tool
carries only a claim and ids, so each finding is a call of
`note_finding`: a file, its line at the head, a grade, and what is
wrong. The file is read at that head through the forge first, so a line
past its end is refused, and so is a path outside the repository. The
reviewer submits through `submit_review`, citing the ids its reads and
findings answered.

**A review passes a gate of its own.** A result of a reviewer's session
cites calls of that session to read the pull request, read its files, or
note a finding, and nothing else. A failure is a result once it cites
them. A success cites only calls that answered without failing, a read
of the pull request among them. The gate reads them from the session's
history and accepts the review as verified; a history past 20,000 steps
is refused, never judged in part. A result of any other kind passes the
gate it passed before, unchanged.

**The reviewer's comment waits for a person.** `comment` is an
integration call that acts outward, so the platform's ceiling holds it
for a person's approval, and the reviewer's own layer runs reads alone.

**The operator ships.** It is built from `records`, a new `operations`
toolset (`list_hosts`, the tenant's hosts with what each offers, and
`read_spend`, its budgets with what each spent), `knowledge`, and
`artifacts`. Its authority is delegated, it has no workspace, and it
asks what the others ask. Every tool it holds reads. It holds no
hand-off, a spawn: a fix it finds leaves as a self-contained objective,
which a person hands to an engineer.

**A kind that only reads is held to it at boot.** The assistant, the
operator, and the reviewer each have a reach: the classes of call they
may make, their authority, and no workspace. A version of any of them,
whoever declares it, that reaches further is refused. The check reads
the whole catalog, the engine's tools included.

**The forge's comment ships with the agents.** A process that wires no
`comment` of its own gets the platform's, over the intake it hands its
root, so every root that ships the reviewer holds the tool it names.

**A role of roles is a lead.** A kind whose toolsets include
`sub_agents` starts the others, such as an engineer on a change and a
reviewer on its pull request, and answers with their reports. It is a
kind like any other; no noun is added.

**Nothing is migrated.**

## Consequences

- A product takes the reviewer and the operator as it takes the other
  shipped kinds, each version pinned: its tool definitions and its
  prompts render the same bytes for every session of that version.
- A matrix version is published only with a row for XL, which the
  reviewer asks. The seeded version holds one; the first version an
  operator publishes after this needs one.
- The reviewer reads only pull requests of an installation its tenant
  connected. Each finding costs one read of a file through the forge.
- The reviewer reads a branch at its head, file by file, and runs
  nothing on it. A check that needs the branch run is a validation, or
  the checks the forge reports.
- The operator reads the tenant's own operations. The work queue's
  lanes as a whole, the sweeps' runs, and spend by matrix version are
  read on the operator plane and from the platform's metrics, which a
  tool's tenant context never reaches.
