# ADR 2077: A pool VM's host fetches its session's archive itself, in compressed parts, each under a key of its own

**Status**: accepted (2026-11-24)

## Context

A session of the cloud pool keeps its workspace's directory as an
archive in the snapshots bucket, and every run that restores it boots a
VM from the pool's image
([ADR 2070](2070-the-cloud-pool-keeps-a-sessions-files-sealed-never-a-disk.md)).
The archive followed the engine's directory snapshots: one plain tar, in
parts, each sealed under the session's key
([ADR 1045](1045-a-vm-workspace-keeps-its-directory-as-sealed-parts-and-starts-again-on-its-base.md)).
Only the runner holds that key, so a restore read each part from the
bucket, opened it, and wrote it into the VM as a relayed write: one item
a part, each part crossing the store twice, one after another. A system
that makes too many calls gets faster by removing calls first, then
folding them, and only then running them at once. A tar of a source tree
compresses several times over.

The exec relay already hands a host an object without the session's
key: the object is sealed under a key of its own, the item keeps that key
under the session's, and the item's detail hands the host the key and a
link signed for that object alone
([ADR 2066](2066-every-file-and-output-an-exec-item-moves-crosses-the-store-by-a-url-signed-for-it-alone.md)).

## Decision

**Compressed in the VM.** The pack is the directory's tar, compressed
with zstd where the VM has it, and a plain tar where it has none. The
archive names how it is packed. The pool's image installs zstd. The
directory's bound holds as it did: the files are measured in the VM
before tar starts, the pack's size is held to the bound before any part
is read, and the runner, which reads the tar out of a compressed pack
only to scan it for an injected secret's value, refuses one that
unpacks past the bound.

**Each part under a key of its own.** Each part is sealed under a fresh
key, bound to where it is kept (`acme.infra.buckets.sealed`), and put at
the engine's place for it, so the session's purge and the pool's sweep
find it as before. The archive names each part by its size, its digest,
and its key, and is kept as any snapshot is, sealed under the session's
key and trusted by its keyed hash. Revoking the session's key leaves
every part's key noise, and the parts with them.

**The VM's host fetches the parts.** A restore hands the host of the
session's VM the parts as `fetch_files` items of the exec relay, 16 parts
to an item, one item after another. Each part is named by its place in
the directory's kept folder, its reference, size, digest, and key. The
relay refuses a fetch that names anything but a part of its own session's
archives. The item's detail signs a GET link for each part alone, good
for the relay's object time. The host fetches an item's parts at once,
straight from the store, opens and checks each against its size and its
digest, and only then writes it. No byte of a part crosses the runner.
The item never moves or removes a part. A part that does not open or
match loses the restore, as an altered part did: its VM goes, and nothing
kept is touched.

**Every archive and every host still restores.** The exec wire moves to
version 4, its floor unchanged. A host below it is handed no fetch: the
runner then reads each part, opens it under its own key, and writes it
as a relayed write. An archive kept before this decision, the engine's
manifest over a plain tar, restores that way too, its parts opened under
the session's key. The unpack reads how the archive is packed.

## Consequences

- A restore's parts cross the store once, from the bucket to the VM, and
  an item moves 16 of them at a time; the runner holds none of them.
- Less crosses the network and less is kept: the archive is the
  compressed pack.
- The pool's archives are the platform's own format beside the engine's.
  A move of the base that changes the engine's directory snapshots
  leaves them as they are.
- A VM whose image has no zstd packs a plain tar, and one whose host is
  older restores through the runner, so neither waits on the image.
- A part the store fails to serve reads to the host as one it refused,
  so a restore lost to a passing store failure parks for a person, as a
  lost restore does.
- The detail of a fetch carries a link per part, 16 at most.
