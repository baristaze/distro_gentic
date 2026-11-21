---
name: distro-scaffold-workspace-provider
description: "Add a workspace provider: a backend that prepares, releases, and purges the workspaces a session's tools run in, at the isolation it can hold and refusing every other, paired with the transport that runs commands in what it prepares, selected by a setting a deployed process refuses when it cannot isolate tenants, with its tests, in the shape of the container provider. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make setup), Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
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

- `<backend>` is the value of `ACME_AGENT_WORKSPACE_BACKEND` that selects it,
  snake case, with `ACME_` read as the tree's prefix. `<Backend>` is its
  CamelCase.
- `--mode` is the `IsolationMode` the backend holds, from
  `infra/src/<name>/infra/agent_workspaces/__init__.py`. A backend holds one
  mode, and refuses every other.
- `--transport` names a transport under
  `infra/src/<name>/infra/transports/` that already runs commands in
  what this backend prepares. Without it, the backend gets a transport
  of its own.
- `--setting`: each knob the backend reads, a field of
  `AgentInfraSettings` in `infra/src/<name>/infra/agent_root.py`, beside
  `agent_workspace_backend`, where `_runtime` reads it.

## Created

The shape of a provider is `AgentWorkspaceContainerImpl` in
`infra/src/<name>/infra/agent_workspaces/container.py`, over
`AgentWorkspaceProviderInterface` in `infra/src/<name>/infra/agent_workspaces/__init__.py`.
The shape of a transport is `TransportContainerImpl` in
`infra/src/<name>/infra/transports/container.py`.

| File | Holds |
|------|-------|
| `infra/src/<name>/infra/agent_workspaces/<backend>.py` | `AgentWorkspace<Backend>Impl(AgentWorkspaceProviderInterface)`; when it reaches its machines through a client, the client's interface, which its constructor takes, a concrete client of it, which refuses every workspace, naming why, where nothing configures it, as `VmsNullImpl` does, and the client's twin (step 5) |
| `infra/src/<name>/infra/transports/<backend>.py` (no `--transport`) | `Transport<Backend>Impl(TransportInterface)` |

## Changed

| File | Change |
|------|--------|
| `infra/src/<name>/infra/agent_root.py` | in `AgentInfraSettings`, `<backend>` in `agent_workspace_backend`'s `Literal` and each `--setting` field; a branch in `_runtime` that answers the provider and its transport as a pair; with a mode below `container`, a row in `AGENT_UNSAFE_IN_CLOUD`; with a client, its field on `AgentInfra`, built once in `configured()`, which hands it to `_runtime`, and set to its twin in `local()`, and its getter on `AgentInfraRoot`, as `vms` and `get_vms` are |
| `infra/src/<name>/infra/root.py` (with a client) | the client's abstract getter on `InfraInterface`, as `get_vms`: arch-check's ASY-02 refuses an interface in `infra` that no getter of the root returns |
| `.env.example` | `<backend>` in the comment on `ACME_AGENT_WORKSPACE_BACKEND`, and each setting, commented, with its default |
| `services/api/tests/test_settings.py`, `workers/maintenance/tests/test_settings.py` | each `--setting` in `LOCAL_DEFAULT_SERVES_THE_CLOUD` with its reason, as `workspace_image` is, since neither process prepares a workspace; `test_every_setting_the_cloud_needs_is_wired` fails on a setting the cloud sets no value for and no reason excuses |
| `infra/tests/test_agent_workspaces.py` | the cases of step 5 |
| `infra/tests/test_transports.py` (no `--transport`) | `TestTransport<Backend>(TransportContract)` |
| `infra/tests/test_agent_root.py` | the backend in the cases of step 5 |
| `infra/README.md` | the backend in the Agent workspaces row, and its transport in the Transport row |

## Procedure

1. A workspace is a cache. `prepare` makes the workspace or finds the
   one it made before for the same ids and spec, and answers it;
   `release` lets the machine go and keeps the files, so the next
   `prepare` finds them; `purge` removes the machine and the files by
   ids alone, and one already gone is no error. Nothing the provider
   holds in memory is needed to find a workspace again. Choose by what
   its `snapshot` keeps. A provider whose snapshot is the whole workspace
   (a container's filesystem, a disk) takes `KeepsWholeMixin`, as the
   container provider does. One whose every instance starts again from
   the workspace's base, so the session's directory alone carries over,
   implements `keeps_directory` (True), `pack`, `read`, `drop`, and
   `restore`, and its `snapshot` takes a base's build alone, as the VM
   provider does (`vm.py`). Where that snapshot would not keep a mounted
   volume, a build (`building=True`) keeps its workspace where the
   snapshot holds it: a container's, in its own layer, with no volume.
2. `check` refuses a spec the backend can never hold and makes nothing.
   Before a new loop's first model call, the platform asks it of the
   session's pin when this process makes the workspace and the pin asks
   more than its isolation, a snapshot or a base: a refusal ends the
   loop with no call spent (`check_pinned`, in
   `om/src/<name>/om/agent_workspaces/impl/tools.py`). `prepare` refuses
   the same before it creates anything:
   `refusal(spec, mode=..., egress=..., limits=...)` answers why the
   backend cannot hold it, and the provider raises `IsolationRefused`
   with it, its `cause` the same text, from `check` and `prepare` alike.
   A spec at another mode is refused, never run at a weaker
   one, and a backend that cannot reach what it needs (its daemon, its
   image) refuses rather than fall back to another backend, as
   `test_a_container_spec_with_no_docker_is_refused_and_never_swapped_for_a_directory`
   holds. A command whose machine vanished under it ends with the exit
   its channel gave, as the container's and the VM's transports end it,
   and the next `prepare` makes the machine again; `AgentWorkspaceLost`
   is raised only where what a workspace is rebuilt from, a snapshot or
   a base, cannot be brought in, as `vm.py` raises it.
3. The provider and its transport are one pair: `_runtime` in
   `infra/src/<name>/infra/agent_root.py` answers both, and the
   transport runs commands only in what the provider prepared, by the
   workspace's own handle. Secrets reach a
   command as the engine's transports pass them, brokered or injected
   by name (`transports/broker.py`, `transports/injection.py`); the
   provider itself holds none. Egress is held where the machine runs,
   as the spec's allowlist says, never by the command.
4. A backend whose mode is below `container` cannot keep one tenant's
   command from another's files, so a deployed process refuses it: its
   row in `AGENT_UNSAFE_IN_CLOUD`, in `agent_root.py`, names the field,
   the value, and the variable, as `host`'s does.
5. The tests reach no real machine in a unit test. A provider that runs
   a command line on this host, as the container provider runs `docker`,
   takes a fake of it in the test file, shape `LocalDocker` in
   `infra/tests/test_agent_workspaces.py`. A provider over a client takes
   the client's twin, written in `src` in the provider's file, shape
   `VmsTwinImpl` in `infra/src/<name>/infra/vms/twin.py`: `local()` sets
   it, and the provider's and the transport's tests import it from there.
   A test that needs the real one is marked `integration` and skipped
   when the machine lacks it, as `TestTransportContainer` is:
   - each spec it cannot hold is refused by `check` and by `prepare`
     before the client is called, a parametrized list shaped as
     `CONTAINER_REFUSES`;
   - a spec at its mode is met; a second `prepare` finds the same
     workspace; its files outlive a `release`;
   - a `purge` by ids removes the machine and the files, and a second
     purge does nothing;
   - with no client reachable, the spec is refused, never met by another
     backend;
   - the backend builds its provider and its transport together, in
     `test_a_workspace_backend_builds_its_provider_and_its_transport_together`
     in `infra/tests/test_agent_root.py`, and, below `container`, a
     deployed environment refuses it, in
     `test_deployed_environments_refuse_the_engines_local_backends`
     there, which takes each row of `AGENT_UNSAFE_IN_CLOUD`;
   - a transport of its own runs the whole `TransportContract`.

Then the gate, `make check`, as After writing in the conventions
runs it. A tree with no `.venv` at its root, as a fresh copy is, runs
`make setup` there once before it: the gate runs the tools it installs.

## Output

As `../_shared/scaffold-conventions.md` states.
