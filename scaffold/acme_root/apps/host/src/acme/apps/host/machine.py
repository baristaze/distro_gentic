"""The host as a machine of the platform's cloud pool runs it: inside a
virtual machine the pool started for one session, so the machine is that
session's wall. It enrolls with the key the pool handed the machine, in its
seed, rather than a tenant's enrollment token, and it claims its session's
work alone, which the platform holds it to.

Its workspace is a folder in the machine, at the VM's level
(`acme.infra.agent_workspaces.machine`). Its commands
run as the host's own user, in Docker's group, so they build and run
containers of their own: the machine's root is theirs through Docker, as a
VM workspace's commands hold their guest whole. Its egress is the machine's,
closed at the machine's network by the pool to what the session's spec
asks. It keeps no snapshot and starts from none: the pool keeps the
machine's whole disk, and starts the machine again from it."""

from acme.apps.host.probe import Probe, Probes, container
from acme.client.types import IsolationMode as HostIsolation


def machine_probes() -> Probes:
    """A machine's probes: its level is the VM's while Docker answers its
    commands, and its metadata endpoint is the pool's to close, which the
    pool does before its session's work comes."""
    return Probes(
        isolation={HostIsolation.vm: machine},
        metadata=lambda: Probe(
            "metadata", True, "the cloud pool closes this machine's metadata endpoint"
        ),
    )


def machine() -> Probe:
    """A VM per session: this host runs in a machine its pool started for one
    session, and Docker answers its commands there."""
    engine = container()
    if not engine.passed:
        return Probe("vm", False, f"a machine of the cloud pool, and {engine.detail}")
    return Probe("vm", True, f"a machine of the cloud pool, and {engine.detail}")
