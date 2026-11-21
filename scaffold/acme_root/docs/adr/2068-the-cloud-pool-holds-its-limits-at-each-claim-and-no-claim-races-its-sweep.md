# ADR 2068: The cloud pool holds its limits at each claim, and no claim races its sweep

**Status**: accepted (2026-11-21)

## Context

The cloud pool starts a VM per session ([ADR
2052](2052-the-cloud-pool-runs-a-vm-per-session-whose-host-pulls-its-work.md)).
Nothing bounded how many it ran, for the platform or for one tenant, so
one tenant's burst started VMs without end, and a VM bills while it
runs. Its warm count was a deploy setting, so moving it took a deploy.

The sweep and a claim also met on the same rows without a rule between
them. The sweep let a warm VM go by destroying it, then deleting its
row, so a session that claimed the VM in between lost it under its
feet. And a VM that the cloud took away after its host enrolled kept its
row: the sweep stopped only a VM that still ran, so the row stayed until
its session's next prepare, holding a place.

## Decision

**The limits are records, read at each claim.** The pool's own limits
are three numbers: the warm VMs it keeps started, the most VMs it holds
at once, and the most one tenant holds. An operator writes them, a new
row per version, so every write stays with who made it. A tenant may
have a maximum of its own in place of the default, one row an operator
writes or clears. Every claim and every refill reads them as they stand.
With no row, the pool's options hold: none warm, 20 at most, 5 a
tenant. `ACME_CLOUD_POOL_WARM` is gone.

**A VM counts until it is let go.** A VM counts against both maxima
from its start or its claim until its row goes, whether it runs, starts,
or stands stopped for its session. A stopped VM bills no compute, but
its session starts it again without asking, so it keeps its place. The
maxima therefore bound the VMs that run, and a count of rows is the
whole count.

**One lock counts and writes.** A claim takes the pool's advisory lock,
counts its tenant's VMs and the pool's, and then binds a warm VM or
writes the new VM's row. The refill counts and writes under the same
lock, and never starts past the maximum. So two claims never pass a
maximum together. A warm VM already counts, so binding one at the
maximum is allowed. Warm VMs stand below the maximum, which a write
holds.

**A warm VM gives way at the maximum.** A session of a size other than
the default, or of another egress, cannot take a warm VM. A restore can:
every VM boots the pool's image, and the restore fills its directory
([ADR 2070](2070-the-cloud-pool-keeps-a-sessions-files-sealed-never-a-disk.md)).
At the maximum, a claim that cannot take a warm VM takes the place of
the oldest idle warm VM, one that started and that no session claimed.
Under the same lock, the warm VM's row goes and the claim's own is
written. The warm VM is destroyed
before the claim's VM starts, so the VMs that run never pass the
maximum. If that destroy fails, the claim's row goes too, and the
sweep destroys the warm VM, which no row holds. A warm VM still
starting keeps its place, and the claim waits. A claim past its
tenant's maximum takes no warm VM's place.

**Past a maximum, the session waits.** A claim past either maximum
starts no VM. It raises the refusal that clears, so the loop parks on
the resource and asks again at its retry, as any workspace that is not
free yet does. Its line is the order of the asks, with no reservation.
The park's cause says that no VM is free yet, or that the tenant holds
as many as it may. It never names a count, the pool's size, or another
tenant's use. The log names which maximum held.

**An operator's write is audited where it belongs.** A write of a
tenant's own maximum, and its clearing, leave an audit event in that
tenant's stream, naming the operator and the value. A write of the
pool's own limits leaves its event in the platform's stream, the system
scope's, which no tenant reads, so the pool's size reaches no tenant.
The operator plane serves them under `/v1/admin`.

**A warm VM's row goes first.** The sweep deletes a warm VM's row
under the claim's lock, and only if no session has claimed it, before it
destroys the VM. If a session claimed it, the sweep leaves it alone. If
the destroy fails, the VM has no row, and the next sweep's pass over
the names no row holds destroys it.

**A VM that died is let go.** The sweep lists the VMs under the pool's
names after it reads the rows. A row whose VM had run by then, and is
listed no more, is one the backend no longer holds, once `state` says
so. The sweep lets it go: its host's credential ends and its row goes.
A warm one goes row first, as above. The sweep runs only where the
process reaches the VMs, since a process that reaches none reads every
VM as gone.

**A VM's host acts only on its session's workspace.** This already
holds, and nothing is added. The pool asks the VM's host to prepare
the workspace only after the host enrolled and the VM is sealed. An
`exec` item goes only to the host its session's binding names, and only
the host's answer to the prepare writes that binding.

## Consequences

- One migration in the core chain: the pool's limits, a row per
  version, and a tenant's own maximum, fenced by its tenant and purged
  with it.
- A claim reads two rows and takes one lock. A claim happens once per
  new VM, never per loop, so the cost stays off the loop's path.
- Lowering a maximum below what is held lets go of nothing. The VMs
  held stay until their sessions let them go, and new claims wait until
  the count falls.
- A dead VM is noticed at the next sweep, not after the silence bound.
  Its session's next prepare starts another, as before.
