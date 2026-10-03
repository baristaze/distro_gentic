---
name: distro-scaffold-work-kind
description: "Add a product's own kind of work: its payload, the lane its payload names, the claimant kind that takes it through the gateway, and, when it needs them, a stream kind with its bounds, registered beside the platform's kinds and handed to every root, with its tests, in the shape of the platform's own product-kinds tests. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-work-kind

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: Sessions Are Work (Kinds of
Work), Placement and Workspace Hosts (Placement, Workspace Hosts),
Watching and Steering (Live Streams).
Lenses: `../../lenses/placement.md`, `../../lenses/watch.md`.
The decision: `../../scaffold/acme_root/docs/adr/2025-a-product-adds-its-own-kinds-through-the-registries-the-platforms-go-through.md`.

## Input

`<KIND> --claimant <claimant> [--stream <stream>]`, and what the work
carries, where it runs, and who claims it, in the arguments or in the
conversation.

Example: `RENDER --claimant batch`, for "a render job carries its frame
count and runs on a node of the batch pool its payload names".

- `<KIND>` is the kind's name in capitals, as `KIND_NAME` in
  `om/src/<name>/om/work/kinds.py` holds it. A name `WorkKind` in
  `om/src/<name>/om/work/types/work_item.py` holds is the platform's:
  stop and say so.
- `--claimant` is the claimant kind in lower case, as `CLAIMANT_NAME` in
  `om/src/<name>/om/placement/kinds.py` holds it. `host` is the
  platform's: stop and say so. A claimant kind the product already
  registered is reused, never registered twice.
- `--stream` names a stream kind in lower case when the work streams
  what a person watches live while it runs (`STREAM_KIND` in
  `om/src/<name>/om/watch/kinds.py`). `step` is the platform's.

A kind a worker of the product's own runs from a lane it serves, with no
claimant, is the guideline's kind of work: `arch-scaffold-worker`, not
this skill. Its name goes in `WorkKind` as that skill says, but in this
base its payload goes in `WORK_PAYLOADS` and its spec, with its
permission, in `WORK_KINDS`, both in `om/src/<name>/om/work/kinds.py`.
It never goes in `ProductKinds`, which refuses a kind with no claimant.

## Created

| File | Holds |
|------|-------|
| `om/src/<name>/om/product_kinds.py` (the first kind) | the product's kinds: each kind's payload, its lane, its `WorkKindSpec`, each claimant kind's `ClaimantKindSpec`, each `StreamKind`, and `PRODUCT_KINDS`, the one `ProductKinds` every root reads |
| `om/tests/unit/test_<kind>_kind.py` | the cases of step 6, `<kind>` the kind's name in lower case |

From the second kind on, `product_kinds.py` exists: the kind is added
to it, and that is no collision.

## Changed

The shape of each part is `om/tests/unit/test_product_kinds.py`, whose
`RenderPayload`, `RENDER_KIND`, `BATCH_CLAIMANT`, and `frames` are a
kind, a claimant kind, and a stream kind a product registers, over
`WorkKindSpec` in `om/src/<name>/om/work/kinds.py`, `ClaimantKindSpec`
in `om/src/<name>/om/placement/kinds.py`, `StreamKind` in
`om/src/<name>/om/watch/kinds.py`, and `ProductKinds` and
`PlatformPorts` in `om/src/<name>/om/root.py`.

The first kind only:

| File | Change |
|------|--------|
| `services/api/src/<name>/services/api/container.py` | `AppContainer.build` passes `ports=PlatformPorts(kinds=PRODUCT_KINDS)` to `over` |
| `workers/maintenance/src/<name>/workers/maintenance/container.py` | `WorkerContainer.build` passes `PlatformPorts(kinds=PRODUCT_KINDS)` to `worker_managers` |
| `workers/session_runner/src/<name>/workers/session_runner/entry.py` | `run(ports=PlatformPorts(kinds=PRODUCT_KINDS))`, both imported inside `main` after the trust store is installed |

When a root already passes ports of the product's, `kinds=` joins them.

## Procedure

1. The registries, the claim, the tenant wall, and the answers for a
   held item are the platform's, in `work/kinds.py`,
   `placement/kinds.py`, `placement/impl/manager.py`, and
   `watch/kinds.py`, and this skill changes none of them. A product
   adds values to them.
2. The payload is a `Platform` model that names where the work runs (a
   pool, a node) by id, and bounds every field a person or a claimant
   sets. The lane is a function of the payload alone, `<claimant>:<id>`
   with the id it names; a kind whose lane reads anything else is
   placed by a payload nobody checked.
3. The `WorkKindSpec`: the name, the payload, the permission whoever
   asks for it holds (`Permission.WRITE` unless the ask says otherwise),
   the lane, and `claimant=` the claimant kind. `ProductKinds` refuses a
   kind with no claimant.
4. The `ClaimantKindSpec`: the claimant kind's name; `claims`, the
   lanes its identity serves and the kinds it takes from each, read off
   the `Claimant` alone (its `id`, `org_id`, and `pool_id`), never off
   anything it sends; and `prefix`, its credential's, a few lower-case
   letters and an underscore that no registered kind and no credential
   of the platform's carries (`root.PLATFORM_PREFIXES`). A kind it names
   is taken only when the kind names it back.
5. With `--stream`: a `StreamKind` with its entries, its bytes, and its
   open streams of one group, each the most one stream of the kind may
   hold, and `claimant=` the `--claimant` kind, which writes it for the
   item it holds. The open streams of every group and the idle time are
   the step's; a kind never sets them. This skill registers the kind and
   adds no stream route: the claimant appends at
   `/v1/claimants/me/items/{item_id}/streams/{kind}`, and a member of the
   item's tenant opens a handle at
   `/v1/work-items/{item_id}/streams/{kind}/live` and reads at
   `/v1/live/items` (ADR 2030). The program on the claimant that appends
   is the product's: name it in the output as what the product still
   needs.
6. The tests, each the shape of its namesake in
   `om/tests/unit/test_product_kinds.py`, over the managers built with
   `product_kinds=PRODUCT_KINDS`:
   - the kind goes to its lane, and only its claimant kind takes it:
     `test_a_products_kind_goes_to_its_lane_and_only_its_claimant_kind_takes_it`,
     with a second claimant kind registered in the test beside
     `PRODUCT_KINDS` that claims the kind from its lane but is not named
     back, as the sibling's `GREEDY` is, so the case holds a registered
     kind out and not only an unknown one;
   - a claimant inside a tenant's wall is never handed another tenant's
     item: `test_a_claimant_in_a_tenants_wall_is_never_handed_another_tenants_render`;
   - a claimant reads and answers only the items it holds:
     `test_a_claimant_reads_and_answers_only_the_items_it_holds`;
   - a write that asks for the kind lands it on its lane, and a payload
     off its shape is refused:
     `test_a_write_that_asks_for_a_products_kind_lands_it_on_its_lane`;
   - with `--stream`, the kind is held to its bounds and the cache's,
     and its writer is a claimant kind of the product's own:
     `test_a_products_stream_kind_is_held_to_its_bounds`,
     `test_a_stream_kind_a_claimant_writes_names_a_claimant_kind_of_the_products_own`.
7. A claimant reaches the gateway as a host does: an owner issues a
   token of its kind for a pool (`/v1/host-pools/{pool_id}/enrollment-tokens`
   with the kind), the claimant enrolls with it at
   `/v1/claimants/enrollments`, and its credential, under its prefix,
   claims, reads, renews, and reports at `/v1/claimants/me/...` (ADR
   2029). The platform issues the credential and serves the routes, so
   the skill adds neither. The program that runs on the claimant is not
   this skill's: name it in the output as what the product still
   needs.

Then the gate, `make check`, as After writing in the conventions runs
it.

## Output

As `../_shared/scaffold-conventions.md` states, and the lane the kind's
items go to.
