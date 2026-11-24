# ADR 2075: The cloud pool keeps warm VMs hibernated, holding no key

**Status**: accepted (2026-11-24)

## Context

A warm VM stands running ahead of demand, so a claim skips a cold boot
([ADR 2052](2052-the-cloud-pool-runs-a-vm-per-session-whose-host-pulls-its-work.md),
[ADR 2068](2068-the-cloud-pool-holds-its-limits-at-each-claim-and-no-claim-races-its-sweep.md)).
It bills its compute the whole time it waits. A cloud can hibernate a VM
instead: the VM writes its memory to its disk and stops, costs its disk
alone, and takes its processes up where they were when it starts again.
A pool could keep more VMs warm for the same money. A claim of one skips
the boot and the disk's first reads, and waits for the memory to come
back from the disk instead.

A hibernated VM's memory lands on its disk. A warm VM's memory holds its
seed, with the one-use key its host trades for a credential. A key on a
disk outlives the VM's run, and the disk is sealed under the pool's key,
never a session's
([ADR 2070](2070-the-cloud-pool-keeps-a-sessions-files-sealed-never-a-disk.md)).

## Decision

**A warm VM may be started to sleep.** The pool's limits name how many
warm VMs stand running, `warm`, and how many sleep, `hibernated`,
together below the most the pool holds. A VM asleep counts toward that
maximum, and the refill starts each kind up to its own count, the
running ones first. A VM started to sleep boots the pool's image under a
one-use key, as any warm VM does, and runs until it has settled:
`settle`, five minutes by default, so its boot is over, its container
engine and its host program are up, and its disk's first reads are done.
EC2 hibernates no instance in its first minutes in any case.

**It sleeps holding no key.** Once it has settled, the sweep ends its
key, only while the row still holds that key and names no session, so
one sweep alone takes it. Then it hibernates the VM, then marks it
asleep. The key in its memory is ended before the memory reaches the
disk, and its host holds no credential: a warm VM's host is refused
enrollment until a session claims it. A host that asks with an ended key
is refused, and stops asking. A VM that fails to hibernate goes, rather
than stay awake.

**A claim wakes it under a fresh key.** A claim at the default size
takes a warm VM that runs, then one asleep, then starts a new one. It
never takes one started to sleep that sleeps not yet. Taking one asleep
writes the digest of a fresh key into its row, in the claim's own
transaction, then hands that key in its seed as it wakes: the path a
stopped VM already takes when it starts again under a new key. On EC2
the seed goes into the instance's first-boot data while it sleeps. The
image reads it again after the resume (`acme-vm-resume.service`) and
starts the host on it, which enrolls for the claiming session alone.
The claim counts as `hibernated` in `acme_cloud_pool_claims_total`, and
its wait for the first command is timed under the same source, so the
readings say where such a claim lands between a warm one and a cold
boot.

**No VM that served a session sleeps.** Only a warm VM's row, naming no
session, is taken to sleep. A session's VM with no host is stopped,
never hibernated, so a session's memory never reaches a disk.

**It is let go in time.** EC2 keeps a VM hibernated 60 days at most. The
sweep lets one asleep go two days before the longest its VMs keep one
so, or past the pool's maximum age, whichever comes first, and the
refill starts another. A VMs backend says whether, and how long, it
hibernates. Where it hibernates none, as on Lima, the tier is off: no VM
starts to sleep, and the local pool works as before.

**The cloud is set up for it at plan.** The cloud pool module's
`hibernation` sets hibernation in the launch template, since an instance
takes it at launch alone, and adds the largest size's memory to the root
disk. A size map that names a type which cannot hibernate is refused at
plan, since a VM of it would fail only as it went to sleep. The module's
output sets `ACME_VM_HIBERNATION`.

## Consequences

- One migration: a VM's row says whether it was started to sleep, and
  since when it sleeps; the pool's limits say how many sleep.
- An image for a pool whose VMs hibernate holds the cloud's hibernation
  agent: `install.sh` with `HIBERNATION=1`.
- Every VM of a template that hibernates has a root disk larger by the
  largest size's memory, whether it ever sleeps or not.
- A VM asleep keeps its seed's ended key on its disk until a claim or the
  sweep lets it go. That key enrolls nothing.
- A VM settles by time, not by a report of its own. A VM that sleeps
  before its host is up still wakes and enrolls; its claim waits longer.
- An operator who sets a hibernated count where the VMs hibernate none
  keeps none asleep, and is told nothing.
