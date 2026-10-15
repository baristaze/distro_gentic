# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.21.0 (2026-10-15)

The platform's nouns name the agent, and its base moves to the engine at
v0.19.0, with the guideline's v0.61.0 beneath it: every layer renames
the nouns a product could own, each namespace has an API document of its
own, and the platform wires in files of its own, through the engine's
root and loop hooks. Each role's own migrations fold into one revision.
Minor; the renames are breaking, and no alias is left.

### Changed

- Breaking: each platform noun a product could own names the agent or
  what it serves, on every surface. Project, Automation, Knowledge,
  Playbook, and billing take Agent; Notification is ParkAlert; the
  fleet, the relay, a delivery, and an arm are the agent fleet, the exec
  relay, the work product, and a contender; the kinds are
  `software_engineer` and `ops_analyst`. Rows stay, and stored values
  move in place, restored on downgrade (ADR 2063) (#172).
- Breaking, from the engine's v0.19.0 and the guideline's v0.61.0, in
  the scaffold and in the platform's own code: the change events, the
  wait lines, `OmBase`, the agent sessions, steps, plans, tool outputs,
  agent workspaces, VMs, spend budgets, language models, and tool
  policies, and the budget scope `agent_project`. The platform's own
  columns that carried the engine's nouns move with them (#174).
- Breaking: the cloud pool's machines are VMs on every surface:
  `POST /v1/hosts/vm-enrollments`, `ACME_HOST_VM_SEED` and
  `ACME_HOST_VM_WORKSPACE`, `deployment/vms`, and `make vm-image` (#174).
- Breaking: the cloud pool's tag is `acme:vm` (was `acme:machine`), and
  its IAM condition reads it, so a deployment whose pool holds VMs, kept
  disks, or a sealed image retags them or ends them before it takes this
  release (#174).
- Each namespace has its own OpenAPI document, generated types, and
  client module, and the platform's operator routes sit in its
  namespace routers (#174).
- The engine's root takes one hooks object, `platform_root` builds the
  platform's managers over it, and each process builds the platform in
  a half of its own. A product declares a namespace in
  `product_namespaces.py` and `product_api.py`. `build_managers` takes
  no platform keyword, and `ProductKinds` and `PlatformPorts` live in
  `platform_root` (ADR 2064) (#173).
- The platform registers its kinds below the root's markers. Its edits
  to the engine's loop (the attached toolsets, the fill-set renewal at a
  new loop, the step before a loop's first call) are a
  `LoopHooksInterface` of its own, and the engine's secret scan, enqueue
  rule, and rule of two read the toolsets it attaches (#174).
- Each role's own migrations are one revision at its head, on the
  engine's folded chains, and a schema dump of each equals the chain's.
  A local database behind that head is made anew (`make reset`) (#174).
- A copy's release-before run leaves out the release before's tests
  that read a renamed table or column (#174).
- The ADRs say the decision that holds, each with one date (#174).

### Removed

- The platform's own path that attached toolsets inside the engine's
  loop: the loop hooks carry them (#174).
- ADR 2013: its standing decision, a validation session as a record of
  its own, is ADR 2024's (#174).
