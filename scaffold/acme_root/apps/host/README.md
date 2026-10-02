# Acme workspace host

The program a tenant installs inside its own wall to run its work there.
It is a client of the gateway, like the CLI, and never a process of the
platform's deployment: it opens every connection outward, and the
platform never calls in.

```bash
uv run acme-host probe        # what this machine would advertise
ACME_ENROLLMENT_TOKEN=hen_... uv run acme-host run   # the first start
uv run acme-host run          # every start after it
```

## What it does

- **Probes at startup.** It checks its trust store, its proxy, that the
  platform answers, and that its clock is within a minute of the
  platform's. A failed check stops it there, never mid-session. Then it
  probes each isolation mode: a VM per session, a container per session,
  a directory run as a dedicated user. It advertises its operating
  system, its shell, its capabilities, and only the modes whose probe
  passed. No setting names a mode.
- **Enrolls once.** With the enrollment token its owner issued, it gets
  a credential of its own, kept owner-only in its home. Every start after
  that picks the credential up; it rotates it at half its life.
- **Claims only what is pinned to it.** It states the version of `exec`
  work it reads, and nothing else. The platform hands it work of its own
  pool, read off its credential.
- **Waits out a failure.** An answer the platform could not serve, a
  429, or a lost connection makes it wait, longer after each in a row,
  and call again with the credential it holds. Only a refused credential
  or a version below the floor stops it.
- **Holds its owner's ceilings.** Its owner writes `ceilings.toml` in its
  home: the projects it serves, its minimum isolation, its egress, the
  paths a result may read, and whether it accepts people's commands.
  Every item it claims is held to them, and to the modes it probed,
  before anything runs. An item that does not say what it needs is read
  as asking the most. Nothing the platform sends changes a ceiling, and
  a host with no ceilings file does not start.

```toml
projects = ["0192f1a4-6c1e-7a51-9b0c-2f8e5d4c3b2a"]   # or "all"
min_isolation = "container"                           # vm, container, or directory
egress = ["github.com:443"]                           # or "open"
readable = ["/srv/work"]
people_commands = false
```

<!-- agents-only
What runs an item is the executor (`agent.ExecutorInterface`). Until the
relay wires one, `ExecutorPendingImpl` runs nothing, and the item's lease
runs out for the sweep to take back. The fields a host reads of an item
are `project_id`, `isolation`, `egress`, `reads`, and `by_person` in its
payload (`ceilings.ask_of`); a payload without them is refused.
-->

## Conventions

- Exit codes: 0 done, 1 the platform refused, 2 a setting or a file on
  the host is wrong, 3 not enrolled, 4 the platform is unreachable at
  startup, 5 a startup probe failed.
- `ACME_API_URL` names the platform. `ACME_HOST_HOME` (default
  `~/.config/acme-host`) holds `credential.json`, mode 600, and the
  owner's `ceilings.toml`. `ACME_HOST_NAME` is the name it enrolls
  under. `ACME_HOST_WORKSPACE_USER` is the user a bare-directory
  workspace runs as.

## Test

```bash
uv run pytest -q apps/host/tests
```
