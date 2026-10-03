---
name: distro-scaffold-station-adapter
description: "Add a station adapter to the station daemon: the one way a station job reaches a real station, with its controlled stop, its baseline, and its operations, named in the owner's stations file and tested over a fake device and through the daemon's fence and guard, in the shape of the daemon's twin adapter. Python."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(make check), Bash(uv run:*), Bash(git status:*), Bash(git show:*)
---

# distro-scaffold-station-adapter

A path that starts with `../` is read from this skill's folder as
`realpath` resolves it.
Conventions: `../_shared/scaffold-conventions.md`.
Sections of `../../distro_gentic_spec.md`: Stations (Leases, The
Station Daemon, The Guard Nearest the Resource), Evidence (Execution
Records).
Lenses: `../../lenses/stations.md`.

## Input

`<adapter> [--device <path>,...] [--operations <operation,...>]`, and
how the station is reached and what its controlled stop and its
baseline are, in the arguments or in the conversation.

Example: `line_protocol --device /dev/station0 --operations move,read`,
for "sends each operation as one line on the station's device and reads
one line back; the stop is the line `STOP`".

- `<adapter>` is the name a station names in the owner's stations file,
  snake case. `<Adapter>` is its CamelCase.
- `--device`: the device paths under `/dev` a station on this adapter
  declares in its `devices`. The adapter opens nothing else.
- `--operations`: the operations a job may hold for it. Unattended, the
  ones the description names, and no other.

## Created

The shape of an adapter is `StationTwinImpl` in
`apps/station_daemon/src/<name>/apps/station_daemon/adapter.py`, over
`StationAdapterInterface` in the same file.

| File | Holds |
|------|-------|
| `apps/station_daemon/src/<name>/apps/station_daemon/<adapter>.py` | the device's interface (what the adapter writes and reads), its implementation over the declared device, and `<Adapter>Impl(StationAdapterInterface)`, which takes the device in its constructor |
| `apps/station_daemon/tests/test_<adapter>.py` | the cases of step 5, over a fake device |

## Changed

| File | Change |
|------|--------|
| `apps/station_daemon/src/<name>/apps/station_daemon/adapter.py` | a branch in `adapter_for`, and the module docstring's line on what the build carries |
| `apps/station_daemon/src/<name>/apps/station_daemon/stations.py` | `<adapter>` in `ADAPTERS`, and the adapter in the docstring's example table |
| `apps/station_daemon/README.md` | the adapter, and the agents-only block's line on what the build carries |

## Procedure

1. An adapter is the only code that reaches the station. The daemon
   hands it one operation at a time, after the fence checked the lease's
   token and the guard held the command to the owner's limits
   (`stations.refusal`). The adapter never checks a limit, never raises
   one, and never reads a token: those are the daemon's, and a limit the
   adapter enforced instead would move with the adapter.
2. `name` is `<adapter>:<station name>`, as the twin's is, since a run's
   record names what served it. `provenance` is `real`: the twin is the
   only adapter that says `twin`, and an adapter that reaches a real
   station never claims less.
3. `stop` is the station's declared controlled stop
   (`Station.controlled_stop`). It needs nothing from the platform and
   nothing a job set up, so it works when the control plane is slow or
   gone and after any operation failed. `restore` puts the station back
   at `Station.baseline` and is safe to repeat.
4. `run` answers an `Outcome`: `ok` false, with what the station
   reported in `readings`, for an operation the station refused or
   failed. An operation the adapter does not know is `ok` false with the
   reason in `readings`, never run. So is a device that does not
   answer: the daemon counts each `Outcome` into the run's report, and
   an exception out of `run` leaves the job with no report. It opens only the
   paths in `Station.devices`. A setting the adapter needs beyond them is
   a key of the station's table: add it to the known keys and to
   `Station` in `stations.py`, refused with `BadSetting` when it is
   wrong, as `_station` refuses the others.
5. The tests build the adapter over a fake device that records what it
   was sent and answers as the station would:
   - each operation sends what the station expects and answers its
     `Outcome`; an unknown operation, and one the station refuses, are
     `ok` false;
   - `stop` sends the controlled stop with no platform, and after a
     failed operation; `restore` twice leaves the baseline;
   - `name` and `provenance` are as step 2 says;
   - a stations file naming `<adapter>` loads, and one naming a device
     outside `/dev` is refused, shape `apps/station_daemon/tests/test_owner_stations.py`.
     Its case for an unknown adapter names one this build lacks; when
     that name is `<adapter>`, give the case another;
   - through the daemon, shape `test_a_command_past_a_limit_is_refused_and_recorded_in_the_run`
     in `apps/station_daemon/tests/test_daemon.py`: a command past a
     limit never reaches the fake device, and the run's record names the
     adapter.

Then the gate, `make check`, as After writing in the conventions
runs it.

## Output

As `../_shared/scaffold-conventions.md` states, and the line the owner
adds to a station's table to use it: `adapter = "<adapter>"`.
