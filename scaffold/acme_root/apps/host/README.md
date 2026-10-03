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
  paths a result may read, whether it accepts people's commands, and how
  many items it runs at once.
  Every item it claims is held to them, and to the modes it probed,
  before anything runs. An item that does not say what it needs is read
  as asking the most. Nothing the platform sends changes a ceiling, and
  a host with no ceilings file does not start.
- **Prepares the workspaces of its pool.** A session pinned to its pool
  asks a host of the pool to prepare its workspace. The host that claims
  the ask makes it to the session's isolation, a container per session,
  and answers where it is: from then on the session's calls come to this
  host. One it cannot make is answered as refused, so another host of
  the pool may. When another host holds the workspace already, this
  host's goes.
- **Shares its proxy and its CA, under open egress alone.** A command in
  a workspace with open egress goes through the proxy the host's
  environment names, without any credential in its URL, and trusts the
  CA file `SSL_CERT_FILE` names, which its container holds read-only.
  Nothing else of the host's environment reaches it. A workspace with no
  egress gets neither, and no secret may land in their variables.
- **Lets go of an instance when asked.** The platform asks the host
  that holds a session's workspace to release it once no run accounts
  for it past a grace, after it has pushed the checkout's work. The host
  stops the instance it made and keeps its files, so the session's next
  call here starts it anew over them. A release runs and reads nothing,
  so only the tenant fence applies: it lets go only of what this host
  made for that session and tenant.
- **Runs a tool call once, and stops it at once.** An `exec` item it
  claims is a command or a file operation in a workspace it holds. It
  runs it through its own transport, a container per session, sends
  what it prints back a part at a time, and pushes how it ended, each
  with the hash of the bytes it sends. It renews its lease while the
  command runs, and waits out a renewal or a result the platform fails
  to take while the lease lasts. Items run side by side, so a long
  command holds up no other call. It holds one control stream open to
  the platform, which wakes it to claim at once and stops a command at
  once, and opens it again with the credential it holds whenever it
  ends. An item past a
  ceiling is answered as refused, so the agent reads why. A bare
  directory runs only as the host's dedicated user, which no transport
  here does yet, so an item at that mode is refused.

```toml
projects = ["0192f1a4-6c1e-7a51-9b0c-2f8e5d4c3b2a"]   # or "all"
min_isolation = "container"                           # vm, container, or directory
egress = ["github.com:443"]                           # or "open"
readable = ["/srv/work"]
people_commands = false
items_at_once = 4
```

<!-- agents-only
What runs an item is the executor (`agent.ExecutorInterface`), the
relay's in `relay.ExecutorRelayImpl`, over the engine's transports by
isolation mode (`main.host_transports`). A `WORKSPACE` prepare is made by
the provider of its spec's mode (`main.host_workspaces`) and answered
through `ApiClient.answer_prepare`. A release lets go of the instance the
provider of its spec's mode holds for the session and the host's tenant,
and is answered through `ApiClient.answer_release`; a purge is logged and
left to its lease. The fields a host reads
of an item are `project_id`, `isolation`, `egress`, `reads`, and
`by_person` in its payload (`ceilings.ask_of`); a payload without them is
refused. What the item runs it reads from the gateway while it holds it
(`ApiClient.exec_detail`), never from the payload (ADR 2004).
-->

## Conventions

- Exit codes: 0 done, 1 the platform refused, 2 a setting or a file on
  the host is wrong, 3 not enrolled, 4 the platform is unreachable at
  startup, 5 a startup probe failed.
- `ACME_API_URL` names the platform. `ACME_HOST_HOME` (default
  `~/.config/acme-host`) holds `credential.json`, mode 600, the owner's
  `ceilings.toml`, the host's own secret store, `secrets`, owner-only and
  keyed by tenant first, and `records/`, where its transport keeps how
  each command ended. `ACME_HOST_NAME` is the name it enrolls under.
  `ACME_HOST_WORKSPACE_IMAGE` (default `python:3.14`) is the image a
  container workspace runs. An image holds Python, for the session's tools,
  and `git`, since a pinned session's repository is checked out and pushed
  inside its workspace: an image without `git` fails a session with a
  repository before its first model call.
  `ACME_HOST_PULL_TIMEOUT_SECONDS` (default 900) is how long the pull of
  that image may run when a prepare finds it absent; the image is large,
  and a pull cut short leaves nothing.
  `ACME_HOST_WORKSPACE_USER` is the user a bare-directory workspace runs
  as.

## Test

```bash
uv run pytest -q apps/host/tests
```
