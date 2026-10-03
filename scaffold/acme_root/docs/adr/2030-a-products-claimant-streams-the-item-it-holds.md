# ADR 2030: A product's claimant streams the item it holds

**Status**: accepted (2026-10-03)

## Context

A product registers its own stream kinds (ADR 2025), and its claimant
claims through the gateway with a credential of its kind (ADR 2029). A
long job on the product's own machines produces live output that people
watch while it runs. Yet no claimant could write a stream: the writer of
a product's streams was its own code, and the route a viewer read them
through, and that viewer's authorization, were the product's to build. A
product that built them put a side channel beside the tenant wall, and
the wall of every read rested on its code.

The platform already holds every part such a channel needs: the
claimant's credential and the item it holds under its claim token
(ADR 2029), a product's stream kinds and their bounds (ADR 2025), and a
live read by a short-lived handle (ADR 2007).

## Decision

**A stream kind names the claimant kind that writes it.** A
`StreamKind` takes a `claimant`, a claimant kind of the product's own.
`ProductKinds` refuses at boot a kind that names any other, the host
among them, since a host holds no item a stream is bound to. A kind
that names none is written by the product's own code alone.

**A claimant writes only what it holds.** With its own credential, a
claimant appends to a stream of a kind its own kind writes, for an item
it holds, under the claim token its claim was handed
(`POST /v1/claimants/me/items/{item_id}/streams/{kind}`). The item is
held as its read, its renewal, and its report hold it: claimed by this
claimant, in its tenant, of a kind its kind takes, under a live
credential (`hosts.held_as`). A stream adds one more: the lease has not
lapsed. A claim whose lease lapsed writes nothing, though no sweep has
requeued the item yet, so a claimant that missed its renewal renews
before it writes again (`409`). Any other item, and any other kind, is
the same `404`, and nothing lands.

**An append is bounded.** One append carries at most 64 entries and
64 KiB of their bytes, refused before anything reads it. An entry's
number is at most 10^14 - 2: the shared cache spells an entry's id from
its number, and past that it spells no id, so the entry would land
nothing and say so to no one. It spends the credential's budget of
writes, as every call of a claimant's does (ADR 0059). Each stream is
then held to its kind's bounds, its oldest entry going first, never its
newest.

**What crosses is verified by hash.** An entry's bytes cross the
tenant's wall, as a host's part does, so each entry carries the crossing
its sender declared of them: a `stream_part`, its SHA-256, and its size
(ADR 2014). The bytes are checked against it before anything reads
them, and an append with one entry that does not match is refused
whole, `422 crossing_refused`, before anything lands. The hash is the
entry's own rather than the append's, so an entry's bounds are what the
claimant sent: a hash over the joined bytes would not see a boundary
moved.

**The group is the item's.** A stream of a claimant's kind sits in the
group of the item it was written for, keyed by the kind (ADR 2025).

**A member reads it as a session's is read.** A viewer who may read the
item's tenant asks for a handle to the item's streams of one kind
(`POST /v1/work-items/{item_id}/streams/{kind}/live`). It is the same
signed grant as a session's, for the item, the kind, and the viewer,
under a purpose of its own, so a session's handle never reads an item's
streams and an item's never reads a session's. A read
(`GET /v1/live/items?handle=`) answers to the handle alone and reads
from the entry after the last one the reader names. An item of another
tenant opens no handle.

## Consequences

- No migration and no table: the streams are the shared cache's, as
  every stream is.
- `StreamKind` takes `claimant`, and `KindStreamsInterface` answers the
  writer of a kind. The watch is built with a product's kinds' streams
  (`build_watch(..., kind_streams=...)`), and reaches the hosts and the
  work managers; with none, every such stream is not found.
- The lease check is the stream's alone. A read, a renewal, and a report
  still hold an item until the sweep requeues it.
- The live-read key signs both handles. A process without one refuses
  every read of either.
- `distro-scaffold-work-kind` sets the claimant on a stream kind it adds
  that its claimant writes, and names the platform's routes instead of
  the product's.
