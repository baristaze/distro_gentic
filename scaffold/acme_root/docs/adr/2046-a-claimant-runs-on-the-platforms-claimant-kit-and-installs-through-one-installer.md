# ADR 2046: A claimant runs on the platform's claimant kit, and installs through one installer

**Status**: accepted (2026-10-07)

## Context

The platform serves every claimant kind through one code path
([ADR 2029](2029-a-products-claimant-enrolls-and-claims-the-way-a-host-does.md)):
an enrollment token of a kind, a rotating credential under its prefix,
and the identity read off it. Without a client half of the platform's
own, the host's is the only copy, and a product with a claimant writes
the rest again: the credential file and its modes, enrollment once,
rotation at half its life, what a refused credential stops, the
backoff, a journal of reports not yet sent, and an installer with the
host's hardening. A fix to any of them reaches each copy only by hand,
and the credential and the unit's walls are where a copy that drifts
costs most.

## Decision

**What every claimant runs is a kit of the client: `acme.client.claimant`.**
A host and a product's claimant import it, as the placement checker
already lets a host import the client.

- **The credential** is kept owner-only and written whole or not at
  all: a temporary file at mode 600, flushed, then moved over the one
  before. It is rotated at half its life, one rotation at a time, and
  while a work runs too: a claimant runs each work inside
  `Claimant.keeping_alive`, which rotates it when due every beat.
- **Enrollment** happens once, with the token the owner issued, or the
  live credential held for the same platform is picked up. A credential
  the platform refused (401 or 403) is never sent again.
- **The calls are the kind's.** A kind gives how it enrolls and rotates
  (`RoutesInterface`). A product's claimant uses `/claimants/...`
  (`Claimant`): claim, renew, and report. The host keeps its own calls
  and what is the host's alone: its probes, its ceilings, the relay.
- **A report is kept before it is sent.** The journal deletes it once
  the platform records it, sends it again while the platform does not
  answer, and claims nothing in the meantime. One whose claim lapsed
  waits for a later claim of its item and lands under it, so the work
  never runs twice. One refused for its shape is kept for a person.
- **Its settings** are read under a prefix and a kind:
  `<PREFIX>_API_URL`, `<PREFIX>_ENROLLMENT_TOKEN`, `<PREFIX>_<KIND>_NAME`,
  and `<PREFIX>_<KIND>_HOME`. The host's are the same names they were.

**One installer installs every claimant on Linux:
`deployment/claimant/install.sh`.** It takes the kind, the unit's name,
the user, the environment prefix, and the settings file's example, and
renders one unit, `claimant.service`, with the host's walls. A kind adds
to them through its own step, a hook that writes the unit's drop-ins.
The host's installer is that script given the host's names, and its
step binds the owner's ceilings and sets up its rootless engine.

## Consequences

- A product's claimant holds no credential code and no unit of its own:
  a fix to either reaches every kind at its next release.
- The host's credential file names its claimant `claimant_id`; the kit
  reads `host_id` as the same field.
- The host's ceilings bind moves from its unit to its drop-in,
  `ceilings.conf`. The unit still does not start without the file.
- `make host-check` installs a second kind beside the host and holds
  that its unit, its user, and its settings carry that kind's names.
- The kit leaves out the calls that carry a claim token as a header (an
  item's read, a stream's read): the client sends no header a call
  names, and that change is its own.
- A claimant's program keeps the host's exit codes, which the unit
  reads: 1 refused, 2 a bad setting, 3 not enrolled, 4 the platform not
  yet reached. Only 4 and a crash restart it.
