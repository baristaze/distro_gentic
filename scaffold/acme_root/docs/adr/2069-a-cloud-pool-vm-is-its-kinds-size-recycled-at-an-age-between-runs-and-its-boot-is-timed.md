# ADR 2069: A cloud pool VM is its kind's size, recycled at an age between runs, and its boot is timed

**Status**: accepted (2026-11-21)

## Context

The cloud pool starts a VM per session ([ADR
2052](2052-the-cloud-pool-runs-a-vm-per-session-whose-host-pulls-its-work.md))
within the limits its operators write ([ADR
2068](2068-the-cloud-pool-holds-its-limits-at-each-claim-and-no-claim-races-its-sweep.md)).
Three things were left open.

A kind could ask its workspace raw CPUs and memory. A cloud sells
machine types, not raw CPUs, so the cloud's VMs refused any such ask,
and every VM there ran the launch template's one type. A warm VM served
only a spec that asked nothing.

A VM that served a session across runs lived until its session ended.
It kept every change its commands made, and the image it booted,
however old.

How long a new VM takes to boot decides how many should stand warm, and
nothing measured it.

## Decision

**A kind asks a size by name.** A spec's limits name a size: `xs`, `s`,
or `m`. One that names none gets `s`. The deployment maps each name it
allows onto a machine type, with its CPUs and its memory, in one setting,
`ACME_CLOUD_POOL_SIZES`, which the cloud pool module writes as its
`sizes` output. A start on the cloud names the type; a start on Lima
takes the CPUs and the memory. A size the map does not name is refused
for good, with its cause, before any VM starts. An ask of CPUs, memory,
or processes on the pool is refused the same way, so a VM is never met
with a size its spec did not ask. Every other provider refuses a size,
as it refuses any limit it does not enforce; a VM's own host holds it,
since the pool started the VM to it.

**The cloud role launches the map's types alone.** The module's policy
denies a start of any instance whose type the map does not name, and
any change of an instance's type to one. The launch template's type is
the map's `s`, so a start that names none is still one of the map's.

**Warm VMs are the default size.** A claim takes a warm VM only when
its spec asks the default size and no restore. A claim of another size
starts a VM of its own, within the same maxima.

**A VM is recycled at its run's end, past its age.** A VM older than the
pool's maximum age, 72 hours by default, is let go at its run's end,
right after the run's work was pushed. The session's next loop starts
another, from its kept state when it has one. It goes then, and not at
the next prepare, because only the run's end knows its work was kept: a
push that did not land leaves the work on the VM alone, and the run's
end raises before it reaches the recycle. Only a VM whose disk is a
cache is recycled. A VM kept by snapshots is let go at every run's end
that snapshots it, and one whose snapshot did not land holds what no
snapshot holds, so its age does not let it go. The sweep never lets a
session's VM go for its age, so none goes under a running loop. A warm
VM past its age goes at the sweep, its row first as ADR 2068 holds, and
the refill starts another.

**An idle VM goes after its kind's grace, as before.** No session has a
time budget of its own. The grace bounds an idle VM, and the bounds of
its loops a busy one.

**A cold start's boot is a metric.** When a VM's host enrolls, a VM that
its session's claim started records `acme_cloud_pool_boot_seconds`, from
its row's start to the enrollment; every VM boots the pool's image
([ADR 2070](2070-the-cloud-pool-keeps-a-sessions-files-sealed-never-a-disk.md)).
A warm claim records none, since its boot was over before
the claim, and so does a VM started again on its own disk. The row
tells them apart: a cold start is bound to its session as its row is
written, a warm VM at its claim, and a start again at its new start. The
enrollment is where the time is exact, whichever process waited on it,
and a boot that outlasts a prepare's wait is still recorded.

## Consequences

- No migration. The size is the spec's, the age is the row's, and the
  cold start is read off the row's two times.
- A deployment that names no map takes the module's defaults: `m7g`
  types of 1, 2, and 4 CPUs. Lima starts its VMs with the map's CPUs and
  memory, so a local `s` VM holds 2 CPUs and 8 GiB.
- A kind that asked raw CPUs or memory of the pool is now refused, and
  asks a size instead.
- A VM that turns 72 hours during a run lives until that run ends.
- The metric's `source` label is bounded, by two values.
