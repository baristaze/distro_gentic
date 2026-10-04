# ADR 2020: An installation maps to one tenant

**Status**: accepted (2026-10-03)

## Context

The spec's Intake routes the external events that arrive through the
guideline's inbound queue. A system that delivers to the platform, a
forge or a chat, names the installation the delivery came through by its
own id, which is the system's, never the platform's, and names no tenant
until a tenant claims it. The ingress must find the one tenant a
delivery belongs to before anything is queued, and never reach another.

A system's ids are often short and sequential, so a tenant that could
claim an installation by typing its id could claim another tenant's, or
the next one made, and read every event it carries.

## Decision

**A tenant connects an installation with the system's grant.** The system
hands the person who installs the platform a grant naming the
installation. A person who manages the tenant's members hands that grant
to the platform, in person. The integration checks it and answers the
installation it names. The id a person types is never read.

**One tenant an installation.** The mapping's unique index is over the
integration and the installation, across every tenant. A second tenant's
connection of a connected installation is a conflict, and the first
tenant keeps it.

**The ingress finds the tenant before it queues.** It reads the tenant
that connected the delivery's installation in the system scope, since no
tenant is known yet, and queues the event under that tenant. A delivery
whose installation no tenant connected is refused, and nothing is queued.
Nothing in a delivery names a tenant: an org's id is the platform's,
never a system's installation.

## Consequences

- The read by installation is one of storage's enumerated cross-tenant
  reads, and a transition from the request stage.
- Each integration checks its own system's grant. Its twin signs its
  grants as it signs its deliveries.
- A tenant that removes the platform from its system keeps the mapping
  until the tenant goes, and the system then sends nothing for it.
