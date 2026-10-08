---
name: distro-scaffold-work-kind
description: "Add a product's own kind of work: its payload, the lane its payload names, the claimant kind that takes it through the gateway, with its program on the platform's claimant kit and its install through the one claimant installer with the kind's names and the groups it grants, and, when it needs them, a stream kind with its bounds, registered beside the platform's kinds and handed to every root, with its tests, in the shape of the platform's own product-kinds tests and the workspace host. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(uv lock:*), Bash(uv sync:*), Bash(chmod:*), Bash(git status:*), Bash(git show:*)
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
The claimant's program and its install:
`../../scaffold/acme_root/docs/adr/2046-a-claimant-runs-on-the-platforms-claimant-kit-and-installs-through-one-installer.md`,
`../../scaffold/acme_root/docs/adr/2047-a-kind-grants-its-claimants-groups-in-its-unit-and-the-check-allows-exactly-those.md`,
`../../scaffold/acme_root/deployment/claimant/README.md`.

## Input

`<KIND> --claimant <claimant> [--grants <group>,...] [--stream <stream>] [--reads <stream>]`,
and what the work carries, where it runs, and who claims it, in the
arguments or in the conversation.

Example: `RENDER --claimant batch`, for "a render job carries its frame
count and runs on a node of the batch pool its payload names".

- `<KIND>` is the kind's name in capitals, as `KIND_NAME` in
  `om/src/<name>/om/work/kinds.py` holds it. A name `WorkKind` in
  `om/src/<name>/om/work/types/work_item.py` holds is the platform's:
  stop and say so.
- `--claimant` is the claimant kind in lower case, as `CLAIMANT_NAME` in
  `om/src/<name>/om/placement/kinds.py` holds it. `host` is the
  platform's: stop and say so. A claimant kind the product already
  registered is reused, never registered twice. Its program and its
  install take its name too: `<claimant>` in snake case for the kind,
  the package, and the paths, and `<name>-<claimant>` in kebab case for
  the distribution, its command, the unit, and the user, in the forms
  the conventions give `<name>`.
- `--grants` names each group the claimant's work needs on its machine:
  one that opens a file of the machine to it, or the group of an
  account it runs work as. Without it, the claimant holds no group but
  its own. It is this skill's flag, never the installer's: the
  installer reads the grants from the unit (step 9).
- `--stream` names a stream kind in lower case that the work writes
  while it runs, what a person watches live (`STREAM_KIND` in
  `om/src/<name>/om/watch/kinds.py`). `step` is the platform's.
- `--reads` names a stream kind in lower case that the claimant reads
  while it runs, what the product's own code sends it.
- Each direction is a stream kind of its own. A work that streams a log
  out and reads cues in takes `--stream <log> --reads <cues>`: two
  kinds, never one kind that sets both `claimant=` and `reader=`. A run
  for a work kind the product already registered adds only its new
  stream kind to `product_kinds.py` and that kind's cases to
  `test_<kind>_kind.py`, and registers nothing twice.

A kind a worker of the product's own runs from a lane it serves, with no
claimant, is the guideline's kind of work: `arch-scaffold-worker`, not
this skill. Its name goes in `WorkKind` as that skill says, but in this
base its payload goes in `WORK_PAYLOADS` and its spec, with its
permission, in `WORK_KINDS`, both in `om/src/<name>/om/work/kinds.py`.
It never goes in `ProductKinds`, which refuses a kind with no claimant.

## Created

| File | Holds |
|------|-------|
| `om/tests/unit/test_<kind>_kind.py` | the cases of step 6, `<kind>` the kind's name in lower case |
| `apps/<claimant>/pyproject.toml` | the distribution `<name>-<claimant>` over `<name>-client` and `typer`, with its command of the same name, shape `apps/host/pyproject.toml` |
| `apps/<claimant>/README.md` | what the program does, the command that installs it, and what stays the product's, shape `apps/host/README.md` |
| `apps/<claimant>/src/<name>/apps/<claimant>/__init__.py`, `main.py` | the program on the claimant kit, step 8 |
| `apps/<claimant>/src/<name>/apps/<claimant>/work.py` | `work`, the product's, step 8 |
| `apps/<claimant>/tests/test_<claimant>.py` | the cases of step 10 |
| `deployment/<claimant>/<claimant>.env.example` | its settings, shape `deployment/host/host.env.example`, step 9 |
| `deployment/<claimant>/install.sh` | the kind's names over the one installer, step 9 |
| `deployment/<claimant>/dropin.sh` (`--grants`) | the kind's hook, which grants its groups, step 9 |

The files under `apps/<claimant>/` and `deployment/<claimant>/` are
made for a claimant kind the product has not registered. One it
registered already has its program and its install: write neither,
and name in the output that its `work` now takes `<KIND>` too, and
each group of `--grants` its `dropin.sh` does not grant yet.

## Changed

The shape of each part is `om/tests/unit/test_product_kinds.py`, whose
`RenderPayload`, `RENDER_KIND`, `BATCH_CLAIMANT`, and `frames` are a
kind, a claimant kind, and a stream kind a product registers, over
`WorkKindSpec` in `om/src/<name>/om/work/kinds.py`, `ClaimantKindSpec`
in `om/src/<name>/om/placement/kinds.py`, `StreamKind` in
`om/src/<name>/om/watch/kinds.py`, and `ProductKinds` and
`PlatformPorts` in `om/src/<name>/om/root.py`.

| File | Change |
|------|--------|
| `om/src/<name>/om/product_kinds.py` | the kind's payload, its lane, and its `WorkKindSpec`; its claimant kind's `ClaimantKindSpec`, unless the product registered it already; with `--stream` or `--reads`, each its `StreamKind`; each in `PRODUCT_KINDS`, the one `ProductKinds` the product declares |
| `pyproject.toml`, `pyrightconfig.json` (a new claimant kind) | the member `apps/<claimant>` and its distribution `<name>-<claimant>` beside the host's, in each list that names the host's: the workspace's members and sources, the tests' paths, and pyright's |
| `uv.lock` (a new claimant kind) | `uv lock` once the member is in, then `uv sync --all-packages`, so the gate finds it |

Every process's entry point hands its root `PRODUCT_KINDS`: `build` of
the API's, the session runner's, and the maintenance worker's
container. So no container changes. An entry point of the product's that
sets ports of its own sets `kinds=PRODUCT_KINDS` among them.

## Procedure

1. The registries, the claim, the tenant wall, and the answers for a
   held item are the platform's, in `work/kinds.py`,
   `placement/kinds.py`, `placement/impl/manager.py`, and
   `watch/kinds.py`, and this skill changes none of them. A product
   adds values to them. So are the claimant kit,
   `clients/python/src/<name>/client/claimant/`, and the installer,
   `deployment/claimant/`: a product's claimant imports the one and runs
   the other, and changes neither.
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
5. With `--stream` or `--reads`: a `StreamKind` for each, with its
   entries, its bytes, and its open streams of one group, each the most
   one stream of the kind may hold. The `--stream` kind sets `claimant=`
   the `--claimant` kind when the claimant writes it through the gateway
   for the item it holds; one the product's own service writes has
   none. The `--reads` kind sets `reader=` the `--claimant` kind, which
   reads, for the item it holds, what the product's own code writes; it
   never sets `claimant=`. The open streams of every group and the idle
   time are the step's; a kind never sets them. This skill registers
   the kind and adds no stream route. The claimant appends at
   `POST /v1/claimants/me/items/{item_id}/streams/{kind}`, and a member
   of the item's tenant opens a handle at
   `/v1/work-items/{item_id}/streams/{kind}/live` and reads at
   `/v1/live/items` (ADR 2030). The claimant reads at
   `GET /v1/claimants/me/items/{item_id}/streams/{kind}?after=<stream>:<last>`,
   its claim token in the `Claim-Token` header (ADR 2038); the product
   never adds a route of its own for it. The program on the claimant
   that appends or reads, and the product's code that writes a stream
   its claimant reads, are the product's: name each in the output as
   what the product still needs.
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
   - with `--stream` or `--reads`, each stream kind is held to its
     bounds and the cache's:
     `test_a_products_stream_kind_is_held_to_its_bounds`; a `--stream`
     kind that sets `claimant=` names a claimant kind of the product's
     own as its writer:
     `test_a_stream_kind_a_claimant_writes_names_a_claimant_kind_of_the_products_own`;
     and a `--reads` kind names one as its reader:
     `test_a_stream_kind_a_claimant_reads_names_a_claimant_kind_of_the_products_own`.
7. A claimant reaches the gateway as a host does: an owner issues a
   token of its kind for a pool (`/v1/host-pools/{pool_id}/enrollment-tokens`
   with the kind), the claimant enrolls with it at
   `/v1/claimants/enrollments`, and its credential, under its prefix,
   claims, reads, renews, and reports at `/v1/claimants/me/...` (ADR
   2029). The platform issues the credential and serves the routes, so
   the skill adds neither.
8. The program runs on the claimant kit, `<name>.client.claimant` (ADR
   2046), and holds no credential, enrollment, rotation, backoff,
   journal, or lease code of its own: the kit does each, so a fix
   reaches every kind at the next release. `main.py` names the kind and
   the prefix once, `KIND = "<claimant>"` and `ENV_PREFIX`, the tree's
   upper snake prefix (`<PREFIX>` below). Its `run` command builds
   `Claimant(ClaimantSettings.from_env(ENV_PREFIX, KIND), client_for)`,
   with `client_for` shape `build_client` in
   `apps/host/src/<name>/apps/host/main.py`, starts it, and turns as the
   loop in `clients/python/README.md` does. `run` stays a subcommand,
   since the unit starts `<command> run`: as the one command, typer
   keeps it one only under an `@app.callback()`. Each item a turn hands
   it goes to `work` once, and its answer is reported:
   `ReportOutcome.done` for `None`, `ReportOutcome.failed` with the
   reason for a reason, and with the exception's text for one `work`
   raises. It exits with the host's codes, which the unit reads, shape
   `_guarded` in that `main.py`: 1 refused (`CredentialRefused`), 2 a
   bad setting, 3 not enrolled (`NotEnrolled`), 4 the platform not yet
   reached; only 4 and a crash restart it. `async def work(item,
   claimant) -> str | None`, in `work.py`, is the product's: write its
   signature, a docstring of what it gets, and a body that raises
   `NotImplementedError`, and name it in the output as what the product
   still needs. A work that outlasts its lease renews it with
   `claimant.renew`, timed by the kit's `LeaseClock`; a call of the
   kind's own, such as a stream's append (step 5), goes through
   `claimant.client()`, never a client of its own.
9. The claimant installs through the one installer,
   `deployment/claimant/install.sh` (ADR 2046), never an installer, a
   unit, or a step that makes its user of its own.
   `deployment/<claimant>/install.sh` holds the kind's names alone,
   shape the last lines of `deployment/host/install.sh`: the person's
   flags (`--token-file`, `--api-url`, `--name`, `--no-start`) first,
   and the kind's names last, so no flag renames the kind. Its header
   says how a person runs it, as the host's does. Its last line:

   ```bash
   exec "${HERE}/../claimant/install.sh" "$@" \
     --kind <claimant> --unit <name>-<claimant> --user <name>-<claimant> \
     --env-prefix <PREFIX> --command <name>-<claimant> \
     --settings "${HERE}/<claimant>.env.example" --dropin "${HERE}/dropin.sh"
   ```

   `--dropin` is there with `--grants` alone. The settings example holds
   the three lines the installer fills, `<PREFIX>_API_URL=`,
   `<PREFIX>_<CLAIMANT>_NAME=`, and `<PREFIX>_ENROLLMENT_TOKEN=`, the
   last two empty (`<CLAIMANT>` the kind in capitals), and each setting
   the work reads. With `--grants`, `dropin.sh` writes
   `$CLAIMANT_DROPIN/groups.conf` with one `SupplementaryGroups=` line
   that names each group, as `deployment/claimant/README.md` shows. A
   device file stays hidden by the unit's `PrivateDevices=yes` whatever
   the group: what opens one is the kind's own drop-in, named in the
   output as what the product still needs. It never adds the user to a
   group (`usermod`, `gpasswd`): the unit's check refuses every group no
   drop-in grants, and the installer passes it exactly the drop-ins'
   grants (ADR 2047). Both scripts are executable (`chmod 755`): a
   person runs the one, and the installer refuses a hook that is not.
10. The tests of the program, in `apps/<claimant>/tests/test_<claimant>.py`:
    - the program, its install, and its settings name one kind and one
      prefix: `install.sh` passes `--kind` `KIND` and `--env-prefix`
      `ENV_PREFIX`, the settings example holds the three lines the
      installer fills under those names, and `claimant_env` of
      `settings.py` in the kit, given the example's lines, reads the
      URL, the name, and the token from them; with `--grants`,
      `dropin.sh` grants exactly its groups:
      `test_the_program_its_install_and_its_settings_name_one_kind`;
    - the program answers `--help`, which the installer runs once it
      builds the release: `test_the_program_answers_help`;
    - an item a turn hands the program goes to `work` once and is
      reported with its answer, done for none and failed with a reason
      for one, over a stand-in for `Claimant`:
      `test_an_item_is_worked_once_and_reported_with_its_answer`.

Then the gate, `make check`, as After writing in the conventions runs
it.

## Output

As `../_shared/scaffold-conventions.md` states, the lane the kind's
items go to, and, for a new claimant kind, the command a person runs
on its machine, as root:
`deployment/<claimant>/install.sh --token-file <file> --api-url <url>`.
