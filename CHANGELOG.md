# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.16.0 (2026-10-11)

The platform's base moves to the engine at v0.15.0: `read_artifact`,
workspace snapshots and bases, a fork at the spawn, and a VM workspace
on a machines interface. A workspace stays a cache, and a session may
now keep its whole workspace: its snapshot stays on its workspace's side
of the wall. A project's environment is built once where its workspaces
run, and every session starts from it sealed. The cloud pool runs a VM
per session, the same host program inside, its disk kept by the cloud's
own snapshots. The result gate counts a success only after a baseline
at its base, and only runs at the check versions the policy declares.
Minor: nothing is reversed.

### Added

- From the engine's v0.15.0, in the scaffold: `read_artifact`;
  workspace snapshots (a run keeps a `snapshot` workspace whole at its
  end, a restore, a rewind, a fork at the spawn); workspace bases built
  once per tenant; and the VM workspace provider over
  `acme.infra.machines`, local on Lima. The engineer at version 7 and
  analysis at version 4 read a kept result back (#145).
- A durable workspace: an agent kind chooses `cache` or `snapshot`, and
  a project may narrow it to a cache. A cloud workspace's snapshot goes
  to the platform's bucket; a hosted workspace is snapshotted by its host
  through the relay, into the host's own store, the platform holding the
  reference and its hash. A host advertises snapshotting only when it
  probed it. A restore travels with the prepare and keeps its tree
  through the branch's sync; a take of control restores before the
  hand-over; a purge and a key's revocation erase a session's snapshots
  everywhere. Lenses WSP-12 and WSP-13, ADR 2050, migration core
  `202610110551` (#146).
- A project's environment: an image, setup commands, and the
  registries its setup may reach, at `PUT` and `DELETE
  /v1/projects/{id}/environment`. The engineer at version 8 pins it as
  its base and keeps egress `none`; a host builds it once into its own
  store. Lens WSP-14, ADR 2051, migration core `202610110736` (#147).
- The cloud pool runs a VM per session: one machine per session, from
  the session's environment or its latest snapshot, running the host
  program with a one-use key, holding no platform credential; a warm
  count; a machine with no host stopped, its disk kept until its
  session ends; an erase finished by the sweep. Machines on EC2 behind
  the engine's interface, with the Terraform module `cloud_pool`, and on
  Lima locally. Lens PLC-21, ADR 2052, migration core `202610110914`
  (#148).

### Changed

- The result gate counts a success only when a baseline at the
  delivery's base ran before the head's latest validation, and a run
  only at the check version the policy declares now; one rule,
  `rules.baseline`, serves the gate and the acceptance harness. The
  engineer at version 6 takes a baseline again when its base moves.
  ADR 2053 (#144).
- The platform's own `held()` is `held_instances()`, and every platform
  provider and fake takes the engine's `snapshot`, `base`, and
  `building` (#145).
