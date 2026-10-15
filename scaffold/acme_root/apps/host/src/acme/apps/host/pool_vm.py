"""The host as a VM of the platform's cloud pool runs it: inside a
VM the pool started for one session, so the VM is that
session's wall. It enrolls with the key the pool handed the VM, in its
seed, rather than a tenant's enrollment token, and it claims its session's
work alone, which the platform holds it to.

Its workspace is a folder in the VM, at the VM's level
(`acme.infra.agent_workspaces.pool_vm`). Its commands
run as the host's own user, in Docker's group, so they build and run
containers of their own: the VM's root is theirs through Docker, as a
VM workspace's commands hold their guest whole. Its egress is the VM's,
closed at the VM's network by the pool to what the session's spec
asks. It keeps no snapshot and starts from none: the pool keeps the
VM's whole disk, and starts the VM again from it."""

from acme.apps.host.probe import Probe, Probes, container
from acme.client.types.hosts import IsolationMode as HostIsolation


def pool_vm_probes() -> Probes:
    """A VM's probes: its level is the VM's while Docker answers its
    commands, and its metadata endpoint is the pool's to close, which the
    pool does before its session's work comes."""
    return Probes(
        isolation={HostIsolation.vm: vm},
        metadata=lambda: Probe(
            "metadata", True, "the cloud pool closes this VM's metadata endpoint"
        ),
    )


def vm() -> Probe:
    """A VM per session: this host runs in a VM its pool started for one
    session, and Docker answers its commands there."""
    engine = container()
    if not engine.passed:
        return Probe("vm", False, f"a VM of the cloud pool, and {engine.detail}")
    return Probe("vm", True, f"a VM of the cloud pool, and {engine.detail}")
