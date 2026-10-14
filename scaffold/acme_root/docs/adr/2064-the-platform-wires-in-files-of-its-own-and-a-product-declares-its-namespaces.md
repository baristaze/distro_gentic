# ADR 2064: The platform wires in files of its own, and a product declares its namespaces

**Status**: accepted (2026-10-14)

## Context

The platform is a copy of the engine's scaffold. Each engine release is
merged into it, three ways, from the `scaffold` branch. Every engine file
the platform edits conflicts when the release edits it too. The engine's
roots, registries, and containers are where both grow: each manager, each
namespace, and each option adds an import, a parameter, a construction,
and a field there. A product built on the platform meets the same wall one
layer up: it adds its namespace to the API's registry, its services, its
resolvers, its containers, and the maintenance worker's purges, the files
the platform grows too.

## Decision

**The engine's root takes hooks, and the platform builds over them.**
`acme.om.root.build_managers` keeps its own construction and takes one
`RootHooksInterface` (`acme.om.root_hooks`). It calls each hook once, in
the order it builds: the work and resource kinds, the key service, a face
over the sessions, the tools, and the agents, the gates a call and a
result pass, the transport, the attached toolsets, and what goes with a
purged session. With no hooks it builds the engine's graph as rendered,
so the engine's own suites run on it. `acme.om.platform_root` holds the
platform's half in the engine's shape: `PlatformRootOptions` is what a
process sets on the platform's managers, `PlatformManagers` is the
engine's `Managers` with the platform's beside them, and
`build_platform_managers` is the one call every process makes.

**Each process wires the platform in a half of its own.** The API's
container builds through `platform.container`. Its services root
(`services/impl/platform_root`) holds the platform's services beside the
engine's, and its routers ride beside the engine's registry
(`routers/platform.with_platform`), resolving their services through
`gateway/platform_resolve`. The maintenance worker's `WorkerPlatform`
builds its layers and runs its purges, duties, ticks, handlers, and
delivery providers beside the engine's (`PlatformWorkerLoop`). Each purge
runs before the one it names. The session runner builds through
`build_runner_platform`. Infra holds the platform's capabilities as one
`PlatformInfra`, named once where each root describes, starts, and closes
them, with its settings in `PlatformInfraSettings`. `.env.example` and the
Makefile hold the platform's lines in one trailing block each.

**A product declares a namespace once, at each layer it lives in.** Its
managers and its purges, each with the purge it runs before, go beside
its kinds in `acme.om.product_namespaces`. Its routers and its service
factory go beside its API in `acme.services.api.product_api`. The two are
apart because the object model never imports the API: the maintenance
worker reads the first, and the API reads both. A router names its
service with `product_service`. A namespace served and never declared is
refused at boot, and so is a name the platform hosts. No wiring file
names a product's namespace.

**A toolset's tools live in a module of their own**, under
`platform_agents/tools/`, and their tests beside them.

## The engine's files the platform still edits

`git diff origin/scaffold --stat -- scaffold` still lists engine files.
Each row names a class of them and why no hook or block of the
platform's own can hold the edit. A path matches a row when it starts
with the row's prefix.

| Path | Why it stays |
|---|---|
| `om/src/acme/om/root.py` | It takes the hooks and calls each where the graph is built, and it reads the models layer the platform widened (below). It shrinks to the engine's when the engine's root takes these seams. |
| `infra/src/acme/infra/root.py`, `infra/src/acme/infra/impl/` | The interface names the platform's two getters, since every root serves them and every caller holds an `InfraInterface`. Each root names `PlatformInfra` once and wires the platform's proxy and deployment into its container workspace. The settings take the platform's section, and two of the engine's fields take its values: the `ec2` machines and the workspace image. |
| `services/api/src/acme/services/api/container.py`, `services/api/src/acme/services/api/services/impl/root.py`, `services/api/src/acme/services/api/routers/__init__.py`, `workers/maintenance/src/acme/workers/maintenance/container.py`, `workers/maintenance/src/acme/workers/maintenance/main.py`, `workers/session_runner/src/acme/workers/session_runner/container.py` | Each process's entry hands its half the ports, the agents, and the payments the process sets, and holds what it builds. The services root passes intake and the agent projects to the two engine services the platform widened. The registry rides `with_platform` in one line. |
| `om/tests/contracts/loops.py`, `services/api/tests/test_container.py` | The loops fixture takes the builder it runs on. It also passes the call gate's agent projects and labels, and the attached toolsets, which the loop's own hooks carry at the next base move. The container test counts the platform's build. |
| `om/src/acme/om/work/`, `om/src/acme/om/leases/` | Work kinds are a registry a product extends, an item goes to the lane placement answers, and a resource kind declares its ask's shape and check. These change the engine types' shapes, which no hook carries. |
| `om/src/acme/om/windows/impl/gate.py`, `om/src/acme/om/budgets/`, `om/src/acme/om/models/` | The call gate keys budgets by agent project, counts each call under a version and a plan tier, and settles holds. The models layer carries the matrix's resolver, its face over the manager, and those labels. |
| `om/src/acme/om/agent_sessions/`, `om/src/acme/om/agents/`, `om/src/acme/om/attribution/`, `om/src/acme/om/steps/`, `om/src/acme/om/tools/`, `om/src/acme/om/privacy/`, `om/src/acme/om/events/`, `om/src/acme/om/tenancy/` | A session is org-wide or private and stalls, a loop folds in attached toolsets, a fork is taken at a host, a tool spec declares what the platform reads, a member's removal asks for what the tenant keeps of them, and the sweep asks whether a tenant is gone. Each is behaviour of an engine namespace, upstream or staying. |
| `om/src/acme/om/storage/`, `om/migrations/versions/` | The storage roots hold a getter for each of the platform's namespaces, its scopes, and its logins. A storage root has no seam a layer's tables register through. One engine migration's parent is a migration of the platform's, where the two chains meet in one role's history. |
| `infra/src/acme/infra/machines/`, `infra/src/acme/infra/transports/`, `infra/src/acme/infra/workspaces/`, `infra/src/acme/infra/observability.py`, `infra/src/acme/infra/outages/` | The machines hand a seed, a transport carries the host's network, a container workspace carries its deployment and pulls with a limit, and the platform's metrics sit beside the engine's. These change the capabilities themselves. |
| `integrations/` | The forge, the chat, and the scripted twin's pace are integrations the configured root picks and the settings name. |
| `services/api/src/acme/services/api/` (its other files), `services/api/README.md` | The engine's routes and commands carry the platform's behaviour: a session's agent project, the integration webhooks, the event kinds, admission, and an operator's grant of a tenant's content. The seed of a local org's platform parts is a command of the platform's own. Not now: once a base move conflicts in `main.py`, it joins the platform's half through one hook. |
| `workers/maintenance/src/`, `workers/session_runner/src/`, `apps/cli/`, `ops/` | The loop runs ticks, duties across tenants in recovery, and the fleet's gauges. The runner claims a placed lane and holds warm workspaces. The CLI and the operations tool reach the platform's routes. |
| `clients/` | The document and both clients' types are generated from the copy's whole API, and the clients' calls name its routes. |
| `apps/portal/` | The portal has no registry a layer's pages join. Not now: once the engine's portal ships one, the platform's pages register through it. |
| `deployment/`, `scripts/`, `.github/`, `checkers/`, `docs/`, `.agents/`, `README.md`, `llms.txt`, `pyproject.toml`, `pyrightconfig.json`, `uv.lock`, `pnpm-lock.yaml`, `.gitignore`, `.env.example`, `Makefile`, `om/README.md`, `infra/README.md`, `workers/maintenance/README.md`, `workers/session_runner/README.md` | Each describes, configures, or locks the copy whole: its stack, its cloud, its workflows, its members, its ports, and its documents. `.env.example` and the Makefile keep the platform's lines in their trailing blocks, and only the values a copy names stay in place. |
| `om/tests/`, `infra/tests/`, `integrations/tests/`, `services/api/tests/`, `workers/maintenance/tests/`, `workers/session_runner/tests/`, `apps/cli/tests/`, `clients/python/tests/` | An engine suite reads a behaviour the platform changes above, or a case of the platform's sits among the engine's. A suite the platform only added to sits in a file of its own. Not now for the rest: when a base move conflicts in one, its platform cases move out with the merge. |

## Consequences

- A product declares its kinds, its namespaces, and their API in three
  files, and a base move of the product meets the platform's wiring only
  where the platform itself changed.
- A base move of the platform meets the engine's root, registries, and
  containers only at the hooks, the platform's halves, and the rows
  above. At the next one, the engine's root splits by layer and its loop
  takes hooks of its own. The hooks move into the engine's agent root,
  and the loop's own edits onto its hooks.
- A process the platform's tests build without its half gets the engine's
  graph: a suite of the platform's builds through
  `build_platform_managers` or `contracts.platform_loops`.
- `build_managers` no longer takes the platform's keywords: a caller hands
  them to `PlatformRootOptions`. `acme.om.root` no longer exports
  `ProductKinds` or `PlatformPorts`.
