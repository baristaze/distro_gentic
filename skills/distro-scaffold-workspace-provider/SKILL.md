---
name: distro-scaffold-workspace-provider
description: "Add a workspace provider: a backend that prepares, releases, and purges the workspaces a session's tools run in, at the isolation it can hold and refusing every other, paired with the transport that runs commands in what it prepares, selected by a setting a deployed process refuses when it cannot isolate tenants, with its tests, in the shape of the container provider. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-workspace-provider

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: Workspaces and Isolation (A
Workspace Is a Cache, Isolation Levels, Pinned, Probed, Refused,
Egress), Trust (Secrets by Placement).
Lenses: `../../lenses/workspaces.md`.

## Input

`<backend> --mode <mode> [--transport <transport>] [--setting <name>=<default>,...]`,
and what the backend runs a workspace in, in the arguments or in the
conversation.

Example: `microvm --mode vm --setting workspace_vm_kernel=<path>`,
for "a microVM per workspace, its files on a volume that outlives the
VM".

- `<backend>` is the value of `ACME_WORKSPACE_BACKEND` that selects it,
  snake case, with `ACME_` read as the tree's prefix. `<Backend>` is its
  CamelCase.
- `--mode` is the `IsolationMode` the backend holds, from
  `infra/src/<name>/infra/workspaces/__init__.py`. A backend holds one
  mode, and refuses every other.
- `--transport` names a transport under
  `infra/src/<name>/infra/transports/` that already runs commands in
  what this backend prepares. Without it, the backend gets a transport
  of its own.
- `--setting`: each knob the backend reads, a field of
  `InfraSettings`.

## Created

The shape of a provider is `WorkspaceContainerImpl` in
`infra/src/<name>/infra/workspaces/container.py`, over
`WorkspaceProviderInterface` in `infra/src/<name>/infra/workspaces/__init__.py`.
The shape of a transport is `TransportContainerImpl` in
`infra/src/<name>/infra/transports/container.py`.

| File | Holds |
|------|-------|
| `infra/src/<name>/infra/workspaces/<backend>.py` | `Workspace<Backend>Impl(WorkspaceProviderInterface)`, and the client it reaches its machines through, typed by an interface it takes in its constructor |
| `infra/src/<name>/infra/transports/<backend>.py` (no `--transport`) | `Transport<Backend>Impl(TransportInterface)` |

## Changed

| File | Change |
|------|--------|
| `infra/src/<name>/infra/impl/settings.py` | `<backend>` in `workspace_backend`'s `Literal`, and each `--setting` field |
| `infra/src/<name>/infra/impl/configured.py` | a branch in `_build_runtime` that answers the provider and its transport as a pair; with a mode below `container`, a row in `UNSAFE_IN_CLOUD` |
| `.env.example` | `<backend>` in the comment on `ACME_WORKSPACE_BACKEND`, and each setting, commented, with its default |
| `infra/tests/test_workspaces.py` | the cases of step 5 |
| `infra/tests/test_transports.py` (no `--transport`) | `TestTransport<Backend>(TransportContract)` |
| `infra/tests/test_configured.py` | the backend in the cases of step 5 |
| `infra/README.md` | the backend in the Workspaces row, and its transport in the Transport row |

## Procedure

1. A workspace is a cache. `prepare` makes the workspace or finds the
   one it made before for the same ids and spec, and answers it;
   `release` lets the machine go and keeps the files, so the next
   `prepare` finds them; `purge` removes the machine and the files by
   ids alone, and one already gone is no error. Nothing the provider
   holds in memory is needed to find a workspace again.
2. `prepare` checks the spec before it creates anything:
   `refusal(spec, mode=..., egress=..., limits=...)` answers why the
   backend cannot hold it, and the provider raises `IsolationRefused`
   with it. A spec at another mode is refused, never run at a weaker
   one, and a backend that cannot reach what it needs (its daemon, its
   image) refuses rather than fall back to another backend, as
   `test_a_container_spec_with_no_docker_is_refused_and_never_swapped_for_a_directory`
   holds. A workspace whose machine vanished under a running command
   raises `WorkspaceLost`.
3. The provider and its transport are one pair: `_build_runtime`
   answers both, and the transport runs commands only in what the
   provider prepared, by the workspace's own handle. Secrets reach a
   command as the engine's transports pass them, brokered or injected
   by name (`transports/broker.py`, `transports/injection.py`); the
   provider itself holds none. Egress is held where the machine runs,
   as the spec's allowlist says, never by the command.
4. A backend whose mode is below `container` cannot keep one tenant's
   command from another's files, so a deployed process refuses it: its
   row in `UNSAFE_IN_CLOUD` names the field, the value, and the
   variable, as `host` does.
5. The tests reach no real machine in a unit test. The provider takes a
   fake of its client, shape `LocalDocker` in `infra/tests/test_workspaces.py`;
   a test that needs the real one is marked `integration` and skipped
   when the machine lacks it, as `TestTransportContainer` is:
   - each spec it cannot hold is refused before the client is called,
     a parametrized list shaped as `CONTAINER_REFUSES`;
   - a spec at its mode is met; a second `prepare` finds the same
     workspace; its files outlive a `release`;
   - a `purge` by ids removes the machine and the files, and a second
     purge does nothing;
   - with no client reachable, the spec is refused, never met by another
     backend;
   - the backend builds its provider and its transport together, in
     `test_a_workspace_backend_builds_its_provider_and_its_transport_together`,
     and, below `container`, a deployed environment refuses it, in
     `test_deployed_environments_refuse_local_backends`;
   - a transport of its own runs the whole `TransportContract`.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states.
