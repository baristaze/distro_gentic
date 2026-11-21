# ADR 2070: The cloud pool keeps a session's files sealed, never a disk

**Status**: accepted (2026-11-21)

## Context

A session of the cloud pool kept by snapshots ran on a VM whose whole
disk was its snapshot: an image of the stopped instance
([ADR 2052](2052-the-cloud-pool-runs-a-vm-per-session-whose-host-pulls-its-work.md)).
A disk costs about ten times the workspace's files. It is bound to one
zone, and it is encrypted under a key of the platform's, never sealed
under the session's, so a revocation reached it only through the sweep.

The engine keeps a VM workspace's directory alone, as parts sealed
under the session's key in the buckets, and starts each VM again on its
base
([ADR 1045](1045-a-vm-workspace-keeps-its-directory-as-sealed-parts-and-starts-again-on-its-base.md)).
Its provider packs the directory through a command line on the engine's
host. The pool's VM has none: the platform never calls into it, and its
host pulls its work through the relay.

## Decision

**The directory alone, through the relay.** At the end of a run of a
session kept by snapshots, once what the workspace holds is pushed, the
platform's tools pack the workspace's directory as a relayed command on
the VM's host, and read the pack out as relayed reads, one a part
(`pool_directory`). The command measures the directory and refuses one
past the bound before tar starts, naming both. The tools hold the
pack's size to the bound before any part is read, scan it for an
injected secret's value, and keep each part sealed under the session's
key in the snapshots bucket, with the manifest that names them, as the
engine keeps any directory (`SnapshotStore.keep_parts`). A store that
fails part way removes every part it put, so the snapshot before stays
the latest. A session that keeps no content at rest is refused before
anything is packed.

A relayed file operation reaches the directory alone, so the pack sits
in a folder of the directory's own, `.acme-kept`. No archive holds it, no
measure counts it, and it goes however the snapshot ends, or at the
next pack.

**No disk is kept.** The run's release lets the VM go, its disk with
it. No path of the pool makes an image or a volume snapshot of a disk:
the cloud's backend refuses one, and the pool's role is denied every
call that makes one, whatever another statement allows. The erasures of
disks the pool owed, the disk flag on a snapshot's record, and the boot
metric's source label go: every VM boots the pool's image.

**A restore starts from the image.** The manifest is trusted by its
hash before any VM is asked for. A VM that serves the session for
another snapshot goes first: a restore replaces the VM whole, so what
its commands installed outside the directory comes from the image
again. The next VM is a warm one claimed, or one started from the
image, marked for the snapshot it takes back, so a prepare asked again
while it starts keeps it. Each part is trusted only once it opens under
the session's key and matches its hash, then written into the VM's
`.acme-kept` through the relay; then the directory is emptied around
them and filled. A restore that fails part way lets its VM go, never
left half-restored, and touches nothing kept.

**Kept while the session is active.** The pool records each session
whose files it archives, before the first part is sent, with when.
Its sweep reads the records older than `archive_kept`, 30 days by
default, oldest first, a page at a time. A session active since, by its
own row's last write, has its record moved to then. Any other loses
every archive of it in the bucket, their records, and the pool's. The
session's purge removes its archives with its other snapshots. Its
key's revocation leaves them noise, and takes them from the bucket in
whichever process takes it, the API's included. The pool's record goes
with either.

## Consequences

- One migration: the pool's archive records come, and the erasures it
  owed and the disk flag of a snapshot's record go.
- Each run's end of a session kept by snapshots sends its whole
  directory through the relay, an item a part, each through the store
  twice: the host's upload, then the sealed part. An archive whose
  transfer outlasts its run is the trigger for the host to send its
  parts to the bucket itself, sealed under a key the item keeps under
  the session's.
- Every run of such a session boots a VM, or claims a warm one, and a
  tool it needs at every run belongs in the pool's image.
- A VM's disk needs room for the pack beside the directory, and for
  the parts beside the directory a restore fills.
- The host's user is no root: a file only root may read refuses the
  pack, and a file a restore writes is the host's user's. A session
  refused for such a file is the trigger for the image to let that user
  run tar as root.
- A session idle past the bound finds its archive gone when it comes
  back: its restore is lost, and its loop parks for a person, as a lost
  restore does. Its branch and the work its releases pushed stand.
- A session's older archives stay while it is active, one each run's
  end, as the engine's do.
- `.acme-kept` at the top of a pooled directory is the pool's: what a
  command writes there goes at the next pack.
