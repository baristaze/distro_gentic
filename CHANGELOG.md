# Changelog

The latest release is listed here; every release's notes, older ones
included, stay on its GitHub release. Releases are tagged
`vMAJOR.MINOR.PATCH`; see `CONTRIBUTING.md` for what bumps which
number.

## 0.30.0 (2026-11-21)

The platform's base is the engine at v0.26.0, so a session's first model
call never waits for its workspace, and a kind's loop may run in the
request that asks it. The support dock asks a kind of its own in its
request and shows the answer as it streams. The cloud pool's limits are
operator records, a VM's size comes from its kind, and a session's files
are kept as sealed parts, never a disk image. A person's own client
serves a session's local workspace. Each shipped kind is a folder, with
its prompts in Markdown and its own manuals and knowledge beside them.
Minor, with six reversals:

- a workspace is prepared at the first tool call that reaches it, no
  longer before the first model call;
- a spawn starts only a kind whose `started_by` names an agent;
- `ACME_CLOUD_POOL_WARM` is gone, its count an operator record;
- the cloud pool refuses a raw CPU or memory ask, and a kind asks a
  size by name;
- the cloud pool keeps a session's directory, never its VM's disk, and
  makes no disk image;
- `GET /v1/agent-sessions/{id}/questions`, what a session asks a person,
  moves to `GET /v1/agent-sessions/{id}/unlocks`, and
  `POST /v1/agent-sessions/{id}/questions` asks a request kind.

### Changed

- The platform's base moves to the engine's v0.25.0 and then v0.26.0;
  each move's render is on the `scaffold` branch (#220, #221).
  - A session's first model call never waits for its workspace: the
    cloud pool and the platform's providers check a spec before that
    call, and a platform hook checks a new loop's pinned spec where the
    session is placed, so a pin its placement never holds spends no
    model call. The workspace is prepared at the first call that reaches
    it, and the platform's notice of a changed environment rides the
    engine's `workspace_prepared` hook (#220).
  - The API's request loops pass the trust wall, the playbook gates, and
    the knowledge recall. The rule of two reads a session's pinned
    egress, agent knowledge is recalled through the loop's hooks, and a
    connector's server inside the wall reaches its host's workspace
    (#220).
  - A spawn starts only a kind whose `started_by` names an agent. The
    software engineer, analysis, and the reviewer name a person and an
    agent; the planner, the platform assistant, and the ops analyst a
    person alone (#221).
- Each shipped kind is a folder, `platform_agents/kinds/<kind>/`:
  `kind.py` holds its typed versions, and `prompts/v<N>.md` its prompts,
  each pinned by its digest. Every version renders the text it rendered
  before; a version that held several prompts holds them in one, so its
  cached prefix is written once more. ADR 2073 (#223).
- The cloud pool's warm count, its maximum of VMs at once, and a
  tenant's maximum are operator records, read at each claim and each
  refill, each write audited. A claim past a maximum starts no VM and
  waits on the resource. At the pool's maximum, a claim that takes no
  warm VM takes the place of an idle one. The sweep takes a warm VM's
  row under the claim's lock before it destroys the VM. ADR 2068 and a
  core migration (#216).
- A kind asks its VM's size by name (`xs`, `s`, `m`; `s` by default),
  and `ACME_CLOUD_POOL_SIZES` maps each name onto a machine type. A size
  the map does not name, or a raw CPU or memory ask, is refused before
  any VM starts, and the pool's role launches only the map's types. A
  VM past its maximum age (72 hours) goes at its run's end, once the
  run's work is pushed. ADR 2069 (#218).
- A session of the cloud pool kept by snapshots keeps its workspace's
  directory: at a run's end it is packed in the VM and read out part by
  part, each part sealed under the session's key. A restore takes any VM
  of the pool's image, a warm one included. A failed archive keeps no
  part, and a failed restore touches nothing kept. The sweep removes a
  session's archives 30 days after its last activity, and the pool's
  role is denied a disk image. ADR 2070 and a core migration (#222).
- The support dock asks the support assistant through the question
  routes, and shows its answer as it streams. An answer a park stops
  ends with its cause in the dock, one question runs at a time, and the
  dock still continues only the person's own conversation. A support
  conversation's own page points to the dock. ADRs 2045 and 2071, and
  lens FLT-17 (#224).
- No worker runs a request kind's loop: the stalled sweep passes its
  session over, the runner completes its loop item without running it,
  an agent automation refuses to start one, and a connector refuses to
  attach to one (#224).
- The API's request loops take their models from the matrix, a tenant's
  own keys through the trust wall, and reach agent knowledge and agent
  automations (#224).
- A validation that holds checks with a head part and checks without
  one runs every check with a head part first, and reads its results,
  before any check runs the head's code as the instance's own user. ADR
  2067 (#219).
- The host check runs on Ubuntu 26.04 (#205).

### Added

- `support_assistant`, a kind whose loop runs in the request: it reads
  what the platform assistant reads, holds no hand-off, and changes
  nothing. A product's readers and its object model join it as they
  join the platform assistant (#224).
- `stream()` in `@acme/client` reads a route's server-sent events
  (#224).
- A kind's own `manuals/` come first in its sessions' standing text,
  before a tenant's kind manual, and its own `wiki/` entries are
  recalled, found, and read as the kind's own, never a tenant's and
  never by another kind's session. Lens FLT-16, and INT-09 and INT-10
  hold them. A product declares its kinds as folders beside the
  platform's, `ProductKinds.folders` (#223).
- `agent-session start --workspace local` pins a session to a local
  pool of one, and the CLI serves its workspace from the person's
  machine, for its session's tree alone. `--workspace cloud` starts one
  on the cloud pool. With no client serving, a local session's workspace
  call waits and never moves to the cloud. A local workspace's wall is
  its container. ADR 2072 and lens PLC-24 (#217).
- `acme_cloud_pool_boot_seconds` times each cold start, from its start
  to its host's enrollment (#218).
- The agent-kind skill takes `--started-by` and `--share`, writes a kind
  as a folder, and says when a kind's parent gets a new version (#221,
  #223).
- The staging root's `session_key_holders` test holds that only the API,
  the session runner, and the maintenance worker hold the session key
  (#215).

### Fixed

- A stack that ships the platform's agents no longer also offers the
  example assistant, whose tool shared a name with the platform's and
  stopped the API's boot (#224).
