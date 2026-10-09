# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.15.0 (2026-10-09)

The platform's base moves to the engine at v0.14.0, on the guideline's
v0.59.0 with v0.58.0 in it: a read cache keyed by the tenant's
generation, a notice the channel hands over once, a purge's tenant
context and a member's admission, and an investigator's skill for an
integration gone silent. A resource's owner updates it, a tenant reads
its leases back as a history, a kind may refuse an ask, and a line
answers its places from one replay. A product registers its own
resource kinds, each with its hooks and its ask check, and a kind is a
registered name. Minor: nothing is reversed.

### Added

- From the engine's v0.14.0 and the guideline's v0.58.0 and v0.59.0,
  in the scaffold: `ReadCache`, a read cache keyed by the tenant's
  generation; a notice the portal's channel hands over once; the tenant
  context a purge across tenants acts in (`sweep_context`) and the
  org's gate before a new member is written; `ops-integration-silent`,
  an optional investigator's skill; an owner's update of a resource; a
  lease history at `GET /v1/leases` and in the Python client's
  `lease_history`; and `AskCheckInterface`, a kind's check that refuses
  an ask before anything of it lands. ADRs 0095 to 0098 (#141).
- `ProductKinds.resources` builds a product's resource kinds over its
  managers, as its tools are: each a `ResourceKindSpec` with its name,
  its ask's payload model, its hooks, and its ask check if it has one
  (`leases/kinds.py`). Every root hands the leases manager one
  `ResourceKinds` of `noop` and the product's, and refuses a name
  registered twice at boot. ADR 2049 records it and amends ADR 2025
  (#142).

### Changed

- From the guideline's v0.58.0 and v0.59.0, in the scaffold: a write
  bumps the tenant's generation once its transaction commits; a deleted
  tenant keeps its service context until a pass marks it purged; a
  grant lands only while the request still fits the resource as its row
  stands (`grant_fits`); and a line answers each place and estimate
  from one replay (#141).
- The platform's thirty-two `core` migrations move above the engine's
  new head, `202610091904`, as `202610091905` to `202610091936` in
  order, their SQL unchanged (#141).
- A resource's and a request's kind is a registered name, in the API
  and both clients, never an edit of the base's `ResourceKind`, which
  holds the mechanism's own `noop` alone (#142).
- The base's `ops-integration-silent` replaces the platform's own copy,
  and the spec, FLT-11, and the ops README no longer list it as the
  platform's (#141, #142).
- The API document and the clients' types are regenerated (#141,
  #142).
- The spec, the lenses, and the upgrade skill cite the guideline at
  v0.59.0 and the engine at v0.14.0 (#141).

### Removed

- The clients' `ResourceKind` enum, since a kind is a registered name
  (#142).
