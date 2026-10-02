# Acme station daemon

The program on a station's host, inside its owner's wall, that reaches
the lab's stations. It is a least-privilege client of the gateway, like
the CLI, and never a process of the platform's deployment: it opens every
connection outward, and the platform never calls in.

```bash
uv run acme-station-daemon service-config                 # the device access, for review
ACME_DAEMON_CREDENTIAL=std_... uv run acme-station-daemon run   # the first start
uv run acme-station-daemon run                            # every start after it
```

## What it does

- **Starts with a credential of its own.** Its owner issues the lab's
  first one; the daemon trades it at its first start for its own, kept
  owner-only in its home, and rotates that at half its life.
- **Claims only its lab's work.** It states the version of `station`
  work it reads, and nothing else. What it is handed is read off its
  credential.
- **Fences every command.** It keeps the highest lease token it has seen
  for each station on its disk. A command under a lower one is refused.
  Before it takes a higher one, the station takes its controlled stop and
  its baseline is restored.
- **Holds its owner's limits.** Its owner writes `stations.toml` in its
  home: each station's adapter, the device access it needs, the
  operations it accepts, its baseline, its controlled stop, and its
  limits. Every command is held to them before it runs. Nothing the
  platform sends changes them, and a daemon with no stations file does
  not start.
- **Times its lease on its own clock.** The platform says how many
  seconds a lease has left; the daemon counts them on its monotonic
  clock and renews at half of them. Past them, it runs nothing under the
  lease and stops the station. A renewal the platform refuses, because
  the lease was revoked, stops it too.
- **Keeps working when the platform is gone.** The current job runs to
  its lease's end, then the station stops, and no new job is claimed
  until the platform answers again.
- **Keeps its evidence.** A job's report, every refused command in it,
  is on its disk before it is sent, and stays there until the platform
  recorded it.

```toml
[[stations]]
id = "0192f1a4-6c1e-7a51-9b0c-2f8e5d4c3b2a"   # as the platform named it
name = "station-1"
adapter = "twin"
devices = ["/dev/station0"]
operations = ["apply", "measure"]
controlled_stop = "hold"

[stations.baseline]
speed = 0.0

[stations.limits.speed]
max = 1.0
```

<!-- agents-only
The daemon holds logic on purpose: ADR 2006 is the platform's deviation
from the guideline's DEL-01. A job is data, run through the station's
adapter (`adapter.StationAdapterInterface`); this build carries the twin
alone, which names itself, so every run it serves is a twin's.
`service-config` prints a systemd drop-in with one `DeviceAllow=` line
per declared device and every other device closed.
-->

## Conventions

- Exit codes: 0 done, 1 the platform refused, 2 a setting or a file on
  the host is wrong, 3 not enrolled, 4 the platform is unreachable at the
  start.
- `ACME_API_URL` names the platform. `ACME_DAEMON_HOME` (default
  `~/.config/acme-station-daemon`) holds `credential.json`, mode 600, the
  owner's `stations.toml`, the fence's `fence.json`, and the `reports/`
  the platform has not recorded yet. `ACME_DAEMON_CREDENTIAL` is the
  first credential, read once.

## Test

```bash
uv run pytest -q apps/station_daemon/tests
```
