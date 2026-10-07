# Installing the workspace host

The workspace host ([apps/host/](../../apps/host/README.md)) runs inside
a tenant's wall, as a service of its own. The installers here build it
from a checkout of this repository, at the platform's version, and keep
it to the least it needs
([ADR 2026](../../docs/adr/2026-the-runner-is-a-cloud-service-with-no-workspace-and-a-host-installs-as-a-user-of-its-own.md)).
Each needs [uv](https://docs.astral.sh/uv/) on the machine and the
enrollment token its owner issued.

The host is a claimant, and its Linux installer is the claimant
installer, [`deployment/claimant/install.sh`](../claimant/install.sh),
given the host's kind, unit, user, and prefix, and the host's own step,
`dropin.sh`. A product's claimant installs through the same script under
names of its own ([ADR 2046](../../docs/adr/2046-a-claimant-runs-on-the-platforms-claimant-kit-and-installs-through-one-installer.md)).

## Linux, with systemd

```bash
(umask 077; cat > ~/acme-host.token)      # paste the token, then Ctrl-D
sudo deployment/host/install.sh --token-file ~/acme-host.token \
     --api-url https://api.acme.example --name build-01 --engine rootless
rm ~/acme-host.token                      # host.env holds it now
sudo install -m 0640 -g acme-host /dev/null /etc/acme-host/ceilings.toml
sudoedit /etc/acme-host/ceilings.toml     # the owner's ceilings
sudo systemctl start acme-host
journalctl -u acme-host -f
```

The token comes from a file only root and its owner read, or from
standard input with `--token-file -`, and never from a command line or
an environment: what `sudo` is given there, any user on the machine
reads with `ps`. The installer refuses a token in its environment.

What it makes:

| Path | Owner, mode | What it holds |
|------|-------------|---------------|
| `/opt/acme-host/releases/<version>-<time>` | root, read-only to others | One release, built from the lock; `current` points at the latest |
| `/opt/acme-host/python` | root | The interpreter the releases run on |
| `/opt/acme-host/own-group-only.sh` | root | What the unit starts the host with: it refuses while `acme-host` holds a group beyond its own |
| `/etc/acme-host/host.env` | root, 600 | The platform's URL, the host's name, the first start's token, the proxy and CA file. Written once; edit it there |
| `/etc/acme-host/ceilings.toml` | root, 644 | The owner's ceilings, bound read-only into the host's home |
| `/var/lib/acme-host` | `acme-host`, 700 | The host's home: its credential, its secret store, its records |
| `/etc/systemd/system/acme-host.service` | root | The unit, rendered from `deployment/claimant/claimant.service` |
| `/etc/systemd/system/acme-host.service.d/` | root | The host's drop-ins: `ceilings.conf` binds the ceilings; `engine.conf`, with `--engine rootless`, its engine |

The unit runs the host as `acme-host`, never root. The token is spent
once the host holds its credential. Running the installer again builds
a new release, keeps `host.env`, and restarts the host. The host starts
only once `ceilings.toml` exists: a host with no ceilings does not
start. A host started while the platform is down, or before the
machine's clock is in step with it, is restarted until it starts; one
that needs a person stays stopped, and its journal says why.

### What the unit allows

The host reaches the platform over the network, its container engine
over a socket, and its own state. Nothing else of the machine:

- no capability, no new privilege, no set-uid, no new namespace, a
  system-call filter, and memory that is never both written and run;
- the whole file system read-only, its home the one place it writes,
  `/home` and `/root` absent, and its own `/tmp`;
- its ceilings, its release, and its settings out of its reach to
  change;
- a rootful engine's socket (`/run/docker.sock`) out of reach, since
  that socket is root by another name. The unit hides it as the host
  starts, and the host does not start while `acme-host` holds a group
  beyond its own, such as the engine's: a socket the engine makes again
  later is then out of reach too, since a process's groups are fixed as
  it starts. Take `acme-host` out of the group (`gpasswd -d acme-host
  docker`) and start it again.

`systemd-analyze security acme-host` scores it 1.3, "OK". `make
host-check` holds that score under 1.5 and the rest of this list, on a
container with systemd, and CI runs it. It also installs another kind
through the claimant installer beside the host, and holds that its
unit, its user, and its settings carry that kind's names, behind the
same walls.

### Its container engine

A container per session needs an engine the host's user runs:
[rootless Docker](https://docs.docker.com/engine/security/rootless/).
`--engine rootless` gives `acme-host` the subordinate ids the engine
maps, keeps its user services running while nobody is logged in, and
points the host at the engine's socket, `/run/user/<uid>/docker.sock`:
that directory is the one part of `/run/user` the unit shows the host,
read-only. Then set the engine up with its own tool, as that user, and
restart the host so it probes the engine:

```bash
U="$(id -u acme-host)"
sudo -u acme-host env HOME=/var/lib/acme-host XDG_RUNTIME_DIR="/run/user/$U" \
     dockerd-rootless-setuptool.sh install
sudo systemctl restart acme-host
```

With no engine the host still starts, and advertises no container mode,
so no session is placed on it that needs one.

### Its cloud's metadata service

A machine in a cloud reaches its metadata service, which hands the
machine's own credentials (its instance role, its service account, its
managed identity) to whatever asks from the machine. A workspace's
commands leave as `acme-host`, the user the host and its rootless engine
both run as, so under open egress a command could read them and send
them on. The host tries the metadata addresses as it starts, and while
one answers it refuses every item that asks for open egress; the
installer and the host's journal say so. To let open egress run on such
a machine, drop them for `acme-host`, keep the rule the way the machine
keeps its others (`/etc/nftables.conf`), and restart the host:

```bash
sudo nft add table inet acme_host
sudo nft add chain inet acme_host out '{ type filter hook output priority 0; }'
sudo nft add rule inet acme_host out meta skuid acme-host ip daddr 169.254.169.254 tcp dport 80 drop
sudo nft add rule inet acme_host out meta skuid acme-host ip6 daddr fd00:ec2::254 tcp dport 80 drop
sudo systemctl restart acme-host
```

The rules drop TCP port 80 alone, the port the probe tries: on GCP the
metadata address is also the machine's DNS server, so a rule for every
port would drop the host user's name lookups.

A rule in the unit (`IPAddressDeny=`) does not do it: the engine runs
outside the unit, so the host would find the service closed while its
containers still reach it.

## macOS

```bash
deployment/host/install-macos.sh --token-file ~/acme-host.token \
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
