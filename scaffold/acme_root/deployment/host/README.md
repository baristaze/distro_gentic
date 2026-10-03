# Installing the workspace host

The workspace host ([apps/host/](../../apps/host/README.md)) runs inside
a tenant's wall, as a service of its own. The installers here build it
from a checkout of this repository, at the platform's version, and keep
it to the least it needs
([ADR 2026](../../docs/adr/2026-the-runner-is-a-cloud-service-with-no-workspace-and-a-host-installs-as-a-user-of-its-own.md)).
Each needs [uv](https://docs.astral.sh/uv/) on the machine and the
enrollment token its owner issued.

## Linux, with systemd

```bash
sudo ACME_ENROLLMENT_TOKEN=hen_... deployment/host/install.sh \
     --api-url https://api.acme.example --name build-01 --engine rootless
sudoedit /etc/acme-host/ceilings.toml     # the owner's ceilings
sudo systemctl start acme-host
journalctl -u acme-host -f
```

What it makes:

| Path | Owner, mode | What it holds |
|------|-------------|---------------|
| `/opt/acme-host/releases/<version>-<time>` | root, read-only to others | One release, built from the lock; `current` points at the latest |
| `/opt/acme-host/python` | root | The interpreter the releases run on |
| `/etc/acme-host/host.env` | root, 600 | The platform's URL, the host's name, the first start's token, the proxy and CA file. Written once; edit it there |
| `/etc/acme-host/ceilings.toml` | root, 644 | The owner's ceilings, bound read-only into the host's home |
| `/var/lib/acme-host` | `acme-host`, 700 | The host's home: its credential, its secret store, its records |
| `/etc/systemd/system/acme-host.service` | root | The unit |

The unit runs the host as `acme-host`, never root. The token is read
from the environment, never a flag, and is spent once the host holds its
credential. Running the installer again builds a new release, keeps
`host.env`, and restarts the host. The host starts only once
`ceilings.toml` exists: a host with no ceilings does not start.

### What the unit allows

The host reaches the platform over the network, its container engine
over a socket, and its own state. Nothing else of the machine:

- no capability, no new privilege, no set-uid, no new namespace, a
  system-call filter, and memory that is never both written and run;
- the whole file system read-only, its home the one place it writes,
  `/home` and `/root` absent, and its own `/tmp`;
- its ceilings, its release, and its settings out of its reach to
  change;
- a rootful engine's socket (`/run/docker.sock`) out of reach, even when
  someone adds `acme-host` to the engine's group, since that socket is
  root by another name.

`systemd-analyze security acme-host` scores it 1.2, "OK". `make
host-check` holds that score under 1.5 and the rest of this list, on a
container with systemd, and CI runs it.

### Its container engine

A container per session needs an engine the host's user runs:
[rootless Docker](https://docs.docker.com/engine/security/rootless/),
set up for `acme-host` with the engine's own tool, run as that user.
`--engine rootless` points the host at its socket,
`/run/user/<uid>/docker.sock`, and keeps that user's services running
while nobody is logged in. With no engine the host still starts, and
advertises no container mode, so no session is placed on it that needs
one.

## macOS

```bash
ACME_ENROLLMENT_TOKEN=hen_... deployment/host/install-macos.sh \
     --api-url https://api.acme.example --name laptop-01
```

It builds the release into `~/.local/share/acme-host`, writes a launchd
agent at `~/Library/LaunchAgents/com.acme.host.plist` (mode 600), and
logs to `~/Library/Logs/acme-host.log`. The host's home is
`~/.config/acme-host`, where its owner writes `ceilings.toml`; run the
installer again once it is there, and the agent starts. Its engine is
Docker Desktop's.

The agent runs as the person who installed it, and the installer
refuses root. macOS has no system user to wall the host off with, so on
a Mac the ceilings are their owner's word, not a wall: give a host that
serves others a Linux machine.

## Upgrading and removing

Upgrade by running the installer again from a checkout at the new
version. On Linux, remove it with `systemctl disable --now acme-host`,
then delete the unit, `/opt/acme-host`, `/etc/acme-host`,
`/var/lib/acme-host`, and the user. On macOS, `launchctl bootout
gui/$(id -u)/com.acme.host`, then delete the plist and the two
directories. A removed host keeps its enrollment until its owner revokes
it.
