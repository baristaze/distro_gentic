# Installing a claimant

A claimant is a program on a tenant's machine that enrolls with the
platform, claims the work of its kind, and reports it: the workspace
host, or a product's claimant of a kind of its own. On Linux, each one
installs through one installer, [`install.sh`](install.sh), as a
systemd service that runs as its own system user, behind the walls of
one unit, [`claimant.service`](claimant.service)
([ADR 2046](../../docs/adr/2046-a-claimant-runs-on-the-platforms-claimant-kit-and-installs-through-one-installer.md)).

## A kind's names

A kind installs by giving the installer its names, as root, from a
checkout at the platform's version:

```bash
sudo deployment/claimant/install.sh --kind <kind> --unit <unit> \
     --user <user> --env-prefix <PREFIX> --settings <example file> \
     --token-file <file> --api-url https://api.acme.example \
     [--name <name>] [--command <distribution>] [--dropin <hook>] \
     [--requires <file>] [--no-start]
```

`install.sh --help` says what each flag does and where each file
lands. The host's installer, [`deployment/host/install.sh`](../host/install.sh),
is this script given the host's names.

## A kind's own step

`--dropin` names the kind's hook. The installer runs it as root once the
unit is in place. It writes what its kind adds to the unit's walls as
drop-ins, in `$CLAIMANT_DROPIN`, and does what else its kind needs. The
host's, [`deployment/host/dropin.sh`](../host/dropin.sh), binds the
owner's ceilings and sets up its rootless engine.

## The groups a kind grants

The unit starts its claimant through [`own-group-only.sh`](own-group-only.sh),
which refuses while the claimant's user holds a group beyond its own
and the ones its unit grants. A group someone adds the user to is a
door the walls do not see, and a rootful engine's socket group is root
by another name.

A kind whose claimant needs a group grants it in a drop-in its hook
writes, never by adding the user to the group. Such a group is the
group of an account the claimant runs work as, or the group of a file
the claimant reads or writes:

```ini
# $CLAIMANT_DROPIN/groups.conf
[Service]
SupplementaryGroups=acme-scanner-work
```

A granted group gives the claimant that group's access to what the
unit lets it see, and no more. The unit sets `PrivateDevices=yes`, so
no device file is there to open, whatever group the claimant holds. A
kind whose claimant opens a device shows it in a drop-in of its own,
with `PrivateDevices=no` and a `DeviceAllow=` for that device. That
drop-in is the kind's to write, and the check does not read it.

Once the hook has run, the installer reads the groups the unit's
drop-ins grant and passes exactly those to the check:

```ini
ExecStart=/opt/<unit>/own-group-only.sh --granted acme-scanner-work /opt/<unit>/current/bin/<command> run
```

The check refuses any other group the user holds. It exits 6, and the
unit does not restart it. A grant changed later reaches the check when
the installer runs again. A kind that grants none, like the host, gets
the check with none
([ADR 2047](../../docs/adr/2047-a-kind-grants-its-claimants-groups-in-its-unit-and-the-check-allows-exactly-those.md)).
