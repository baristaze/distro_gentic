# ADR 2038: A product's claimant reads the streams its kind reads, for the item it holds

**Status**: accepted (2026-10-05)

## Context

A product's claimant writes a stream for the item it holds, and a member
of the item's tenant reads it by a handle
([ADR 2030](2030-a-products-claimant-streams-the-item-it-holds.md)).
That carries what the claimant produces to a person. A channel the other
way, from a person to the claimant while its job runs, has no read on
the claimant's side. The product's own code can write such a stream
([ADR 2025](2025-a-product-adds-its-own-kinds-through-the-registries-the-platforms-go-through.md)),
but the claimant cannot read it through the gateway. Without that read,
the product builds a route of its own for it, beside the tenant wall:
the side channel ADR 2030 exists to prevent.

## Decision

**A stream kind names the claimant kind that reads it.** A `StreamKind`
takes a `reader`, a claimant kind of the product's own, beside the
`claimant` that writes it. `ProductKinds` refuses at boot a reader that
is any other, the host among them, since a host holds no item a stream
is bound to. A kind that names none is read by no claimant.

**A claimant reads only what it holds.** With its own credential, a
claimant reads the item's streams of a kind its own kind reads, for an
item it holds, under the claim token its claim was handed
(`GET /v1/claimants/me/items/{item_id}/streams/{kind}`, the
`Claim-Token` header). Each stream is read from the entry after the
last one the claimant names (`after=<stream>:<last>`), as a viewer's
read by a handle is. The item is held as its read, its renewal, and its
report hold it (`hosts.held_as`), and, as for a write, its lease has not
lapsed.

**Every item it does not hold is the same 404.** Another claimant's
item, another tenant's, one handed back, one held under a token the
claim no longer carries, and its own under a lapsed lease are one
answer, and nothing is read. A write answers a lapsed lease with `409`,
so the claimant renews before it writes again. A read answers it as it
answers any item the claimant does not hold, so it learns nothing of
the item past its lease; the renewal's own answer tells it whether it
still holds the item. Any other kind is the same `404`.

**A read spends the credential's budget of reads**, as every read of a
claimant's does
([ADR 0059](0059-authenticated-routes-have-limits.md)). A refused read
spends it too.

## Consequences

- No migration and no table: the streams are the shared cache's, in the
  item's group, keyed by the kind, as ADR 2030's are.
- `KindStreamsInterface` answers the reader of a kind beside its writer,
  and the watch reads a claimant's kind through it (`read_as`).
- A kind may name both a writer and a reader. The product's own code
  writes a kind that names a reader and no writer.
- A member's handle still opens only a kind a claimant writes: a kind
  only read by a claimant is the product's to show its people.
- `distro-scaffold-work-kind` sets the reader on a stream kind its
  claimant reads, and names the platform's route for it.
