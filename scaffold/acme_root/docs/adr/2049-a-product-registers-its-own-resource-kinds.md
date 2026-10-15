# ADR 2049: A product registers its own resource kinds

**Status**: accepted (2026-10-09)

## Context

The guideline's leases grant a scarce resource to one holder at a time
([ADR 0086](0086-a-scarce-leasable-resource-is-leased-under-a-fencing-token.md)),
and a kind registers as a work kind does, with its hooks. The scaffold
names its kinds in an enum, `LeasableResourceKind`, keeps each ask's shape in
`ASK_PAYLOADS`, and builds the leases manager with one hook per kind at
the root. A product built on the platform has scarce resources of its
own, each a thing one holder uses at a time. To add one it would edit
the enum, the table, and the root, which every base move then fights,
while every other kind it adds goes through a registry
([ADR 2025](2025-a-product-adds-its-own-kinds-through-the-registries-the-platforms-go-through.md)).

## Decision

**A resource kind is a registry, and the mechanism's own goes through
it.** A product's kind is a `ProductResourceKind` (`platform_root.py`):
its name, its `LeasableResourceKindInterface`, whose `ASK` is the shape
of its ask, and its `AskCheckInterface` when it refuses some asks.
`ProductKinds.resources` builds a product's over the managers, as its
tools and its actions are built. The platform's root hooks hand the
leases manager each one below the root's marker, beside `noop`, with its
check.

**A kind is a name.** A resource's kind and a request's are a registered
name in lower case, as a work kind's is a registered name in capitals.
`LeasableResourceKind` names the mechanism's own. An ask of a kind no root
registered is `ValidationFailed`, and so is one whose payload is off its
kind's shape. A kind's check runs under the asker's context, and its
refusal comes before anything of the ask lands.

**Its name is never the platform's.** A kind named `noop`, or one
registered twice, is refused at boot.

## Consequences

- No migration: a kind is stored by name in a text column with no
  check.
- The API reads and writes a kind as a string of that shape, so the
  clients carry no `LeasableResourceKind` enum.
- A leases manager built with no product kind holds `noop` alone, with
  its own ask.
