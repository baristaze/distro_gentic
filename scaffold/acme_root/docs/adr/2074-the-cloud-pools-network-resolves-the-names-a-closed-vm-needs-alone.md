# ADR 2074: The cloud pool's network resolves the names a closed VM needs alone

**Status**: accepted (2026-11-24)

## Context

A VM of the cloud pool is closed at its network: the closed group
reaches the gateway alone, by a rule outside the guest, which the
session's commands cannot undo though they hold the VM whole
([ADR 2052](2052-the-cloud-pool-runs-a-vm-per-session-whose-host-pulls-its-work.md)).
A security group does not hold a VM's traffic to the network's own
resolver. Any VM can look up any name there, and the resolver asks that
name's servers on the VM's behalf, so a command could carry data out in
the names it looks up. The wall was open by DNS.

## Decision

**The network resolves the names a closed VM needs, and refuses every
other.** The pool's module (`deployment/terraform/modules/cloud_pool`)
takes those names as `allowed_names`: the gateway's, and the store's
when a VM reaches the store at a name of its own. It makes a DNS
Firewall rule group of two rules. The first allows those names, each
whole. The second, at a lower priority, blocks every other name (`*`)
and answers that it does not exist. An allowed name may answer through
an alias its zone names, as a load balancer's does, so the allow rule
trusts that chain: the chain is the platform's zone's, never the VM's.
The group holds the pool's network, and the network's firewall fails
closed: a lookup it cannot judge is refused. An empty list, or a name
with a wildcard, is refused before a plan.

**The network is the pool's alone.** The group holds every lookup made
in the network, so a service of the platform's there would resolve
nothing but the allowed names. The module's `vpc_id` names a network
only the pool uses, and the platform's own services run in another.

**An open VM resolves the rest publicly.** A VM whose session chose
open egress still needs every other name. Its image routes them
(`deployment/vms/acme-vm-dns`): once the cloud has handed the seed,
every name goes to a public resolver, and the platform's own, the host
the seed's `api_url` names, goes to the network's resolver on the link
DHCP configured. A closed VM reaches no public resolver, since its
group admits the gateway alone. The image writes this under `/run` at
each boot. On Lima it never runs, and the guest keeps the resolver its
hypervisor gives it.

**Not DNS turned off.** The pool's network could serve no DNS at all,
with the gateway pinned by address in the seed. A pin goes stale when
the gateway's load balancer moves, and strands every VM started with
it. The store's addresses change too often to pin, and a host still
needs the gateway's name to check its certificate. A firewall that
allows names leaves the addresses to the platform's zone, where they
change.

## Consequences

- A deployment lists every name a closed VM reaches when it calls the
  module. A name the list misses is refused at the network: a missing
  gateway's name means no VM enrolls.
- On a closed VM, a lookup of another name waits out the public
  resolver before it fails, where the network's refusal was at once.
- The image routes the gateway's name alone to the network. The store
  answers at S3's names, which public DNS holds too, so an open VM
  resolves the store publicly and reaches it by its open egress. The
  trigger to route the store's name as well is a store at a name only
  the pool's network answers.
- No deployment calls the module yet
  ([ADR 2052](2052-the-cloud-pool-runs-a-vm-per-session-whose-host-pulls-its-work.md)).
  The trigger is the same: the platform's cloud account, whose
  environment then gives the pool a network of its own.
