# ADR 2067: A hidden suite runs the head's code apart from what scores it

**Status**: accepted (2026-11-09)

## Context

The hidden link exists to catch a head that games its suite ([ADR
2018](2018-acceptance-judges-records-and-a-sequential-test-stops-only-at-its-boundary.md)).
The fresh executor holds every file the suite reads read-only, and reads
a digest of them after each trial, so no file that scores a run scores
it as the head rewrote it. That closes the files, not the process the
results come from. A runner that loads the head's code runs it inside
the process that writes the results stream, so that code can write a
passing result itself, and no lock on a file stops it. It runs as the
user who owns the tree, the container's root without a capability, so it
can also put its own `stat` and `sha256sum` first on the path and fake
the digest. A container that holds no capability lets no process start
another as a different user. Only what starts the commands from outside,
the transport, can.

## Decision

**A check may run the head's code apart.** A check declares `head`: the
command that runs the head's code, beside `command`, the runner. The
fresh executor runs `head` first, in the tree, as a user of its own, the
head's user, with `{work}` a folder of the trial's own. It then runs the
runner as the instance's own user, and the runner scores what the head's
part left there. The head's part names `{version}` and `{work}`, never
`{out}`. Its exit decides nothing, and both parts share one trial's time.

**The runner runs outside the tree.** Its folder is a copy of the files
the run protects, at the paths the tree holds them, and nothing else of
the tree. Many tools read their configuration or their modules from the
folder they start in, or from one above it: pytest a `conftest.py` and a
`pyproject.toml`, `python3 -m` and `-c` the modules there before the
standard library's. In the tree, the head could hold such a file and the
runner would load it. In the copy, each one is the protected source's or
the base's.

**The head's user owns nothing that scores.** The tree, the runner's
copy, the results streams, and every folder on the path are the
instance's own user's, so the head's code writes no result, changes no
protected file, and plants no tool the digest runs. What it leaves in
`{work}` is all of it the runner reads. Its user is `65534:65534` unless
a root names another, by its id and its group's. An instance whose own
user is the head's refuses the checks before any runs.

**A hidden suite has that shape.** A scenario whose hidden check has no
`head` is refused: its runner would load the head's code, which could
write its result. A check of the visible suite may keep one command; the
hidden link is what catches a head that games it.

**The suite's author keeps what the platform cannot read.** What each
part runs is the suite's own: the platform holds that both are declared,
and where and as whom each runs, never what they do. So the head's part
leaves answers, never verdicts: the head's code runs there, and decides
whatever is decided there, a test run's report included. And the runner
never imports or runs the head's code, nor what `{work}` holds: that
code would run as the runner's user, and could write a passing result.

**The transport carries the user.** A command names the user it runs as
(`CommandSpec.user`), by its id and its group's; one that names none runs
as the workspace's own, as before. A container runs it with `docker exec
--user` and ends its tree as that user, since its own holds no
capability to signal another's processes. A transport that runs every
command as one user, a directory, an account, or a VM, refuses one that
names another, and never runs it as its own.

**The relay hands it only to a host that reads it.** The relay's run
request carries the user, and leaves it out when there is none, so such
an item is the one the release before wrote. `exec` work moves to version
3, whose hosts run a command as the user it names, and the floor stays at
2. A host below 3 would run the command as its workspace's own, so the
relay refuses to send it one that names a user.

## Consequences

- A hidden suite written as one command is refused until its head's
  code moves into `head`. That part calls the head's code and writes
  what it answers into `{work}`. The runner reads those answers and
  decides each case: a suite written with pytest runs its tests there,
  in the runner, over the answers, never in the head's part.
- A runner reads nothing of the tree but the files the run protects. A
  check that needs another file of the head's has its head part leave
  it in `{work}`, as data, never as code the runner runs.
- The head's part writes nothing in the tree. A suite that builds the
  head copies it into `{work}` and builds there.
- A hidden suite runs only where a command can run as a user of its own:
  in a container, in the cloud or on a host of version 3 or later. A pool
  of directories or VMs refuses it.
- A process the head's part leaves behind runs on as the head's user
  until the instance goes. It reaches what that user reaches, and nothing
  of the runner's.
