"""A machine handed a file of its own as it starts, and sealed once it has
read it: how the platform's cloud pool gives each machine the one-use key
its host enrolls with. Nothing else enters a machine from outside.

Two ways hand it over. Through the machines' channel, the hypervisor's own
(`SeedsChannelImpl`): the machine starts, then a command inside writes the
file from its standard input, so the file never appears on a command line.
Or at the start itself, through the cloud's own first-boot data, which the
machine's image reads at each boot, closed once read (the EC2 backend's
`launch_seeded` and `seal`). The file sits on the guest's memory-backed
`/run`, never on its disk, so a snapshot of the disk never holds it."""

from datetime import timedelta

from acme.infra.exceptions import BackendFailed, InfraValidationFailed
from acme.infra.machines import (
    SEED_FILE,
    SEED_FOLDER,
    SEED_OWNER,
    MachinesInterface,
    MachineSpec,
    MachineState,
    SeedsInterface,
)

GUEST_WRITE = (
    "set -eu; umask 077; "
    f"sudo -n install -d -m 0700 -o {SEED_OWNER} -g {SEED_OWNER} /{SEED_FOLDER}; "
    f"sudo -n tee /{SEED_FILE}.partial >/dev/null; "
    f"sudo -n chown {SEED_OWNER}:{SEED_OWNER} /{SEED_FILE}.partial; "
    f"sudo -n mv /{SEED_FILE}.partial /{SEED_FILE}"
)
"""Writes the seed from standard input as the guest's own user, owned by the
host's user alone, whole or not at all."""

PLAIN_WRITE = (
    f"set -eu; umask 077; mkdir -p {SEED_FOLDER}; "
    f"cat > {SEED_FILE}.partial; mv {SEED_FILE}.partial {SEED_FILE}"
)
"""Writes the seed from standard input as the channel's own user, under the
machine's root: the twin's, whose machine is a folder of this host."""


class SeedsChannelImpl(SeedsInterface):
    """The seed written through the machines' channel, once the machine runs,
    by `write`: a shell script that reads it from standard input."""

    def __init__(
        self, machines: MachinesInterface, timeout: timedelta, write: str = GUEST_WRITE
    ) -> None:
        self._machines = machines
        self._timeout = timeout
        self._write = write

    async def launch_seeded(
        self, name: str, spec: MachineSpec, snapshot: str | None, seed: bytes
    ) -> None:
        new = await self._machines.state(name) is MachineState.ABSENT
        await self._machines.launch(name, spec, snapshot)
        try:
            reply = await self._machines.run(
                name, ("sh", "-c", self._write), bound=self._timeout, stdin=seed
            )
            if not reply.ok:
                raise BackendFailed("machine", "seed", reply.reason())
        except BaseException:
            if new:
                await self._machines.destroy(name)
            raise

    async def seal(self, name: str) -> None:
        # The channel is the hypervisor's: nothing in the guest reads the
        # seed but from the file.
        return None


class SeedsNullImpl(SeedsInterface):
    """A process that starts no machine."""

    async def launch_seeded(
        self, name: str, spec: MachineSpec, snapshot: str | None, seed: bytes
    ) -> None:
        raise InfraValidationFailed("this process starts no machine")

    async def seal(self, name: str) -> None:
        return None
