---
name: distro-scaffold-runner
description: "Add a session runner for a loop lane: the product's runner entry point, which passes the platform's runner the same agent kinds, tools, and domain classes the product's API passes, the lane it claims (a plan tier's or a tenant's own), its process in the local stack, and its tests, in the shape of the runner suites' own entry point. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-runner

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: Sessions Are Work (Kinds of
Work, Fair Share), Session Runners, Placement and Workspace Hosts
(Placement, The Relay Transport).
Lenses: `../../lenses/placement.md`.

## Input

`<lane> [--capacity <n>]`, and which tenants the lane serves, in the
arguments or in the conversation.

Example: `loop:enterprise --capacity 2`, for "the tenants on the
enterprise plan have runners of their own".

- `<lane>` is a loop lane as `om/src/<name>/om/placement/rules.py`
  names one: `tier_lane`'s `loop:<tier>`, where `<tier>` matches
  `PlanTier` in `om/src/<name>/om/placement/types/share.py`, or
  `own_lane`'s `loop:org:<org_id>` for a tenant whose share gives it a
  lane of its own. `loop:standard`, the lane `.env.example` sets, is the
  default runner's and needs no skill.
- `--capacity`: how many loops a runner of the lane holds at once,
  `ACME_RUNNER_CAPACITY` with `ACME_` read as the tree's prefix. Without
  it, the default runner's.

## Created

None, unless the product has kinds of its own and no runner entry point yet:

| File | Holds |
|------|-------|
| `workers/session_runner/tests/test_entry.py` (the first runner, with kinds of its own) | the entry point passes the product's catalog to `main`, the case of step 5 |

## Changed

The shape of a runner entry point is `workers/session_runner/tests/e2e_runner.py`,
which passes the runner suites' catalog to `main` in
`workers/session_runner/src/<name>/workers/session_runner/main.py`.

| File | Change |
|------|--------|
| `workers/session_runner/src/<name>/workers/session_runner/entry.py` (the first runner, with kinds of its own) | `run(agent_kinds=..., tool_catalog=..., domain_classes=...)`, the product's catalog, after the trust store is installed |
| `scripts/dev.sh` | a runner process for the lane, `serve --lane <lane>`, beside the default runner's |
| `.env.example` | the lane, in the comment on `ACME_RUNNER_LANE` that says each lane in use has runners of its own |
| `deployment/README.md` | the lane, in the row of the session runner |
| `workers/session_runner/README.md` | the lane, and the catalog the entry point passes |

## Procedure

1. A runner is the platform's worker, whole: the claim, the fair share,
   the writer epoch, and the transport chosen by placement are in
   `main.py`, `fair_share.py`, `runs.py`, and `container.py`, and this
   skill changes none of them. A product adds the catalog it passes and
   the lanes it runs.
2. The catalog: the kinds the platform ships come from `SHIPPED` in
   every process. A product's own kinds, tools, and domain classes are
   passed to the runner's `main` by `entry.py`, the same objects the
   product's API passes to its container (`agent_kinds=` of
   `AppContainer.over` in `services/api/src/<name>/services/api/container.py`),
   imported from one module both read, never listed twice. A session
   starts on a kind the API knows and runs on the runner, so a kind
   only one of them knows fails the session. When the product has no
   kinds of its own, neither `entry.py` nor `test_entry.py` is written.
3. A lane has runners of its own. The binary is the same; a runner of
   the lane is `serve --lane <lane>`, which overrides `ACME_RUNNER_LANE`.
   A loop reaches the lane only through placement: `lane_for` puts a
   tenant's loops in its tier's lane, or in its own when its share says
   so, read from the tenant's fair share, never from the item. A lane no
   share names is idle: say so when no share in the seed or the
   product's plans names `<tier>`.
4. A runner never runs inside the sandbox it drives, and holds no host
   credential: a loop placed in a customer's wall reaches its host
   through the relay, from any runner of its lane.
5. The tests:
   - the entry point passes the product's catalog to `main`, read from
     the arguments `main` receives, with `main` replaced in the test, as
     the API's own tests read the arguments of the calls its container
     makes;
   - a tenant whose share names `<tier>`, or gives it a lane of its own,
     has its loops put in `<lane>`, and a runner of `<lane>` claims them
     while one of the default lane does not, shape
     `test_a_tenants_loops_go_to_its_tiers_lane_or_its_own` and
     `test_each_kind_is_claimed_only_from_its_own_lane` in
     `om/tests/unit/test_placement.py`;
   - every knob the runner reads is still in `.env.example`,
     `test_every_knob_of_the_runner_is_in_the_example_env` in
     `workers/session_runner/tests/test_runner.py`.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states, and the command that
starts a runner of the lane.
