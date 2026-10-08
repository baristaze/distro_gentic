# ADR 2047: A kind grants its claimant's groups in its unit, and the check allows exactly those

**Status**: accepted (2026-10-08)

## Context

The claimant installer's unit starts every claimant through a check,
`own-group-only.sh`, that refuses while the claimant's user holds a
group beyond its own
([ADR 2046](2046-a-claimant-runs-on-the-platforms-claimant-kit-and-installs-through-one-installer.md)).
A group someone adds the user to is a door the unit's walls do not
see: a rootful engine's socket group is root by another name.

Some kinds need a group. One is the group of a file the claimant reads
or writes; another is the group of an account the claimant runs work
as. Under the check such a claimant can never start, so its kind
replaces the unit's start and loses the check whole.

## Decision

**A kind grants a group in a drop-in of its unit, with
`SupplementaryGroups=`, and the check allows exactly the groups the
drop-ins grant.** Once the kind's step has written its drop-ins, the
installer reads the grants as systemd reads them, and renders each into
the unit's start as `own-group-only.sh --granted <group>`. Any other
group the user holds is refused, with exit 6, as before.

- The grant lives in the unit, where `systemctl show` and
  `systemd-analyze security` see it. A membership added in
  `/etc/group` is still refused, unless a drop-in grants that group.
- A granted group gives the claimant that group's access to what the
  unit lets it see, and no more. The unit's `PrivateDevices=yes` hides
  every device file, whatever group the claimant holds. A kind whose
  claimant opens a device shows it in a drop-in of its own, with
  `PrivateDevices=no` and a `DeviceAllow=` for that device. That
  drop-in is the kind's to write, and outside the check.
- The installer takes no list of groups of its own. The check's list
  is the drop-ins' grants by construction, so the two never disagree.
  A kind whose groups follow from its own settings, read by the program
  the install builds, grants them the same way.
- The list is fixed at install. A grant changed later reaches the
  check when the installer runs again; until then, the claimant is
  refused in the new group.
- A kind that grants none, the host among them, keeps the start it had.

## Consequences

- A kind with groups starts under the check and keeps the rest of the
  walls. No kind needs to replace the unit's start.
- Each granted group lands in the unit's start, so the installer holds
  each to a plain name or a gid and refuses any other.
- `make host-check` installs a kind whose drop-in grants two groups. Its
  unit passes exactly those to the check; the kind starts in them, and
  is refused in a third. The host's unit passes none.
