---
name: distro-scaffold-host
description: "Give the workspace host an isolation mode it probes but cannot run yet: the transport that runs a relayed tool call at that mode on the host's own disk, wired into the host's transports by mode, with its probe, its place among the owner's ceilings, and its tests, in the shape of the host's container mode. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-host

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: Placement and Workspace Hosts
(Workspace Hosts, The Relay Transport), Workspaces and Isolation
(Isolation Levels, Pinned, Probed, Refused, Egress), Trust (Four
Identities, Secrets by Placement).
Lenses: `../../lenses/placement.md`, `../../lenses/workspaces.md`.

## Input

`<mode> [--transport <transport>]`, and what runs a session's work at
that mode on the host, in the arguments or in the conversation.

Example: `directory`, for "runs each command in the session's directory
as the host's dedicated workspace user, never as the host's own".

- `<mode>` is a host's isolation mode, a member of `IsolationMode` in
  `om/src/<name>/om/hosts/types/host.py` that `probe.py` probes and
  `host_transports` does not run: `vm` or `directory`. The transport is
  keyed by the engine's mode for it, `IsolationMode` in
  `infra/src/<name>/infra/workspaces/__init__.py`, as `HOST_ISOLATION`
  in `om/src/<name>/om/relay/rules.py` maps them. A mode in neither list
  is a change to the platform's wire types, not this skill's: stop and
  say so.
- `--transport` names a transport under
  `infra/src/<name>/infra/transports/` that already runs commands at
  that mode, such as one `distro-scaffold-workspace-provider` wrote.
  Without it, the host gets a transport of its own.

## Created

The shape of the mode is the container mode: `host_transports` in
`apps/host/src/<name>/apps/host/main.py` builds `TransportContainerImpl`
from `infra/src/<name>/infra/transports/container.py`.

| File | Holds |
|------|-------|
| `infra/src/<name>/infra/transports/<mode>.py` (no `--transport`) | `Transport<Mode>Impl(TransportInterface)`, shape `TransportContainerImpl` |

## Changed

| File | Change |
|------|--------|
| `apps/host/src/<name>/apps/host/main.py` | the transport in `host_transports`, under its engine mode, and the docstring's line on what the host runs |
| `apps/host/src/<name>/apps/host/probe.py` | the mode's probe, when it does not check what the transport needs |
| `apps/host/src/<name>/apps/host/config.py` | a setting the transport reads, `ACME_HOST_*`, with `ACME_` read as the tree's prefix |
| `infra/tests/test_transports.py` (no `--transport`) | `TestTransport<Mode>(TransportContract)` |
| `apps/host/tests/test_relay.py`, `apps/host/tests/test_probe.py` | the cases of step 5 |
| `apps/host/README.md` | the mode in What it does, and the agents-only block's line on the transports by mode |

## Procedure

1. A host runs a relayed `exec` item through the transport its spec's
   mode names (`ExecutorRelayImpl._run` in `relay.py`), and answers an
   item at a mode it has no transport for as refused, `capability_missing`.
   After this skill, an item at `<mode>` runs, and every other refusal
   stands.
2. The transport is built in `host_transports`, in `main.py`, the one
   host module the platform's checker lets build an engine transport:
   `[[tool.distro-check.exception]]` for `PLC-10` in `pyproject.toml`
   names it. A new host module that imports `<name>.infra` fails
   `make distro-check`, and an exception for it is the person's
   decision, as the conventions say. So the wiring stays in `main.py`.
3. A mode is advertised only when its probe passed, and its probe checks
   what the transport needs to run, before the first claim
   (`startup` in `probe.py`). A probe that passes for a mode the
   transport cannot then run is an overclaim: every session that trusts
   the mode runs weaker than it asked. A `directory` runs only as the
   dedicated user `ACME_HOST_WORKSPACE_USER` names, never root and never
   the host's own user, as the `directory` probe holds.
4. The transport holds the engine's contract: one command a call, its
   output streamed in parts, its end recorded under the host's
   `records/`, and a stop that ends it at once. Secrets reach a command
   from the host's own store (`SecretsLocalImpl`), brokered or injected
   by name, as the container mode passes them; the transport reads no
   secret of the platform's. Egress is held by the owner's ceilings and
   by the machine the mode runs in, never by the command.
5. The tests:
   - a transport of its own runs the whole `TransportContract` in
     `infra/tests/test_transports.py`, marked `integration` and skipped
     where the machine lacks what it needs, as `TestTransportContainer`
     is;
   - an item at `<mode>` runs once on the host and streams its output,
     shape `test_a_relayed_command_runs_once_on_its_host_and_streams_its_output`
     in `apps/host/tests/test_relay.py`, over a stand-in transport keyed
     by the mode, as the `relayed` fixture keys one;
   - an item at a mode the host did not probe is still refused, and one
     below the owner's `min_isolation` too, shape
     `test_an_item_past_the_hosts_ceilings_is_refused_at_once`;
   - the probe passes only when what the transport needs is there, and
     a failed one leaves the mode out of the advertisement, shape
     `test_a_host_advertises_only_the_modes_it_probed` in
     `apps/host/tests/test_probe.py`.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states.
