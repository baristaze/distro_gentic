# ADR 2025: A product adds its own kinds through the registries the platform's go through

**Status**: accepted (2026-10-03), amended by [ADR 2029](2029-a-products-claimant-enrolls-and-claims-the-way-a-host-does.md), [ADR 2031](2031-a-product-adds-its-own-kind-of-automation-action.md), and [ADR 2049](2049-a-product-registers-its-own-resource-kinds.md)

## Context

The spec's Sessions Are Work has one session produce several kinds of
work, each running where its environment is. A product built on the
platform has work of its own: a long job on machines of its own, a
secret one of its own resources holds, a live stream of its own, a
check that runs only in its own environment. With no hook for each, it
forks the base, or puts its domain back into the platform.

## Decision

**Each kind is a registry, and the platform's own go through it.**
Five registries, each refusing a name registered twice:

- A **work kind**: its name, its payload, the permission that asks for
  it, its lane read off its payload, and the claimant kind that takes it
  (`work/kinds.py`, `placement/kinds.py`).
- A **claimant kind**: its name, and the lanes and kinds its identity
  claims (`placement/kinds.py`). The host is the platform's.
- A **secret owner kind**: whether an owner is the tenant's, and which
  owner a session is placed on (`trust/owners.py`). The project is the
  platform's, and resolves first.
- A **stream kind**: what each of its streams may hold
  (`watch/kinds.py`). The step is the platform's.
- An **executor**, by the validation environment it runs
  (`evidence/executor.py`). The fresh executor runs `platform`.

A product hands its kinds to every root in one place, `PRODUCT_KINDS`
in `product_kinds.py`, with its agent kinds, its tools, and the classes
they declare. Every process's entry point passes it as
`PlatformPorts.kinds`, so each process builds the same registry. A
work, claimant, secret owner, or stream kind whose name the platform
holds is refused at boot, and so is an executor for the platform's own
environment. An agent kind is refused only at a version the catalog
already holds, so a later version of a shipped kind is accepted.

**The gateway's rule holds for every claimant.** Placement claims for a
claimant only the kinds that name its kind back, from the lanes its
identity names, and a claimant inside a tenant's wall is never handed
another tenant's item. A product's claimant reads its item, renews its
lease, and reports it done or failed only while it holds it, in its
tenant. Any other item is the same `NotFound`, so a claimant learns
nothing of work that is not its own. A report is held to its shape
before anything reads it.

**A secret reaches only the sessions placed on its owner,** whatever
the owner's kind. **A product's stream** is held to its kind's bounds,
in a group of its own, and never loosens the step's. **A check names
its environment,** and its validation runs on that environment's
executor. Every executor's report is held to the same bounds and hash
before it is kept, and the result gate reads the record alike.

## Consequences

- No migration. A kind is stored by name in a text column with no
  check, and a check's environment rides in the policy's checks.
- The work namespace's own kinds keep their payloads in `WORK_PAYLOADS`,
  the guideline's table per kind, which their specs read.
- A product's stream kind sets its entries, its bytes, and its open
  streams of one group. The open streams of every group and the idle
  time bound the shared cache, so they stay the step's, and a product's
  stream never closes a step's sooner than the step's own bounds do.
- A product's work kind names its claimant kind, since no worker of the
  platform's runs it. A kind that names a claimant kind nobody
  registered is refused at boot.
- A product declares the ceiling of each of its own classes beside
  them (`ProductKinds.ceilings`), and the root joins it to the
  platform's, so a product never edits the platform's rules. A ceiling
  of a platform class, of a class not the product's, or of a class the
  platform already caps is refused at boot.
- A product's claimant authenticates as a host does: the product's own
  route resolves its credential to a claimant, then calls placement.
  The platform issues no credential of a product's kind.
- A row asking for a kind its process does not know is refused at the
  relay and ends a dead letter, which an audit event names. Every root
  reads the kinds from the one hand-off so none omits them.
- A change whose checks name two environments takes one validation in
  each, on that environment's executor. Every executor's offer is read
  before any runs, and a check none can run refuses all of them. The
  gate reads every validation at the head, each with its own runs.
- `distro-scaffold-work-kind` adds a kind to a copy.
