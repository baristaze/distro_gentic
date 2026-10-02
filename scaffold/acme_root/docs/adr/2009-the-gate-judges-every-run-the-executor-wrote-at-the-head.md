# ADR 2009: The gate judges every run the executor wrote at the head

**Status**: accepted (2026-10-02)

## Context

The engine's result gate is a port: the platform supplies the one that
knows what evidence is. A success counts only when the project's
validation policy passed at the committed head, on a clean tree, on
results the executor wrote. The checks, their fixtures, and the policy
itself are protected, and a change that touches one voids validation.

Three things are left open. Where the policy lives, since a policy kept
in the tree is a file the agent can change. Whether the gate trusts a
verdict stored with a validation, or judges again. And what a success
that validated nothing ends as.

## Decision

**The policy is a platform record.** A person who manages the tenant
writes it, one per project, by a compare-and-set on its version, and
each write is an event. No tool reaches it, so the agent cannot change
it, and it protects the paths in the tree by pattern. A tool that
changes files reports the paths as its target, and a platform ceiling
denies a call that names a protected one, whatever the kind's defaults
and the tenant's layer allow. The root adds the ceiling to whatever
ceilings it is given.

**The gate judges from the runs.** It reads every validation of the
session at the delivered head and every run each one lists, checks that
each run is its validation's executor's, at that head, from a clean
tree, and judges the current policy against all of them. No verdict is
stored to trust. A check that failed once at the head still counts after
a later pass, so running validation again until it passes does not pass.

**A run is written once.** Runs, validations, and hypotheses and
findings are append-only in `activity`, as the history is (ADR 1002),
and the purge login takes them with their session or their tenant (ADR
1010). A validation lands with every run it lists, or none of them.

**Nothing validated is inconclusive.** A success whose work product did
not change, or whose change the policy asks no check of, ends
`inconclusive`, never `succeeded` and never refused.

**The work product and the executor are ports.** The root wires them;
the loud nulls refuse every read and every run. The engine's null result
gate stays the default of `build_managers`, and a process passes this
gate once it wires a work product.

## Consequences

- A success is only as good as the runs behind it, and every one of them
  is kept.
- A policy change applies to the next judgment, not the next validation:
  a check the policy adds is unmet until a validation runs it.
- A process that wires no work product completes work through the null
  gate, which marks every result unverified.
