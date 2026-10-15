"""The platform's infra: the streams read live while they are written, how a
machine of the cloud pool is handed its seed, and the machines of the
platform's cloud account. Each infra root builds it with one call, names it
once where it describes, starts, and closes its capabilities, and serves its
getters through `PlatformInfraRoot`. Its settings are
`platform_settings.PlatformInfraSettings`."""

from dataclasses import dataclass
from datetime import timedelta

import aioboto3

from acme.infra.breaker import Breaker
from acme.infra.impl.settings import InfraSettings
from acme.infra.impl.valkey import ValkeyConnection
from acme.infra.machines import MachinesInterface, SeedsInterface
from acme.infra.machines.ec2 import MachinesEc2Impl
from acme.infra.machines.seeded import PLAIN_WRITE, SeedsChannelImpl, SeedsNullImpl
from acme.infra.streams import StreamsInterface
from acme.infra.streams.breaker import StreamsBreakerImpl
from acme.infra.streams.memory import StreamsMemoryImpl
from acme.infra.streams.valkey import StreamsValkeyImpl


def unsafe_on_platform(settings: InfraSettings) -> str | None:
    """Why the platform refuses these settings at boot, or None: a VM
    workspace on the platform's cloud machines, since a machine of the cloud
    takes no command from outside, and its host pulls."""
    if settings.workspace_backend == "vm" and settings.machines_backend == "ec2":
        return (
            "ACME_WORKSPACE_BACKEND=vm is refused with ACME_MACHINES_BACKEND=ec2: "
            "a machine of the cloud takes no command from outside, and its host pulls"
        )
    return None


def cloud_machines(settings: InfraSettings, aws: aioboto3.Session) -> MachinesInterface | None:
    """The machines of the platform's cloud account, when the settings name
    them; None for any other backend, which the root builds itself."""
    if settings.machines_backend != "ec2":
        return None
    return MachinesEc2Impl(
        aws,
        region=settings.aws_region,
        timeout=timedelta(seconds=settings.aws_timeout_seconds),
        boot=timedelta(seconds=settings.machine_boot_timeout_seconds),
        template=settings.machine_launch_template,
        subnets=tuple(s for s in settings.machine_subnets.split(",") if s),
        closed=settings.machine_closed_group,
        open_=settings.machine_open_group,
        encrypted=settings.machine_store_encrypted,
    )


@dataclass(frozen=True)
class PlatformInfra:
    """The platform's capabilities over one root's: its streams, and its
    seeds over the root's machines."""

    streams: StreamsInterface
    seeds: SeedsInterface

    @classmethod
    def local(cls, machines: MachinesInterface) -> PlatformInfra:
        """In this process: the memory streams, and seeds handed through the
        twin machines' channel."""
        return cls(
            StreamsMemoryImpl(),
            SeedsChannelImpl(machines, timedelta(seconds=30), PLAIN_WRITE),
        )

    @classmethod
    def configured(
        cls,
        settings: InfraSettings,
        valkey: ValkeyConnection | None,
        breaker: Breaker | None,
        machines: MachinesInterface,
    ) -> PlatformInfra:
        """As the settings pick them: the live streams follow the cache, behind
        the same breaker; a machine of the cloud is handed its seed as it
        starts, and one of Lima's through the hypervisor's channel."""
        streams: StreamsInterface = StreamsMemoryImpl()
        if valkey is not None and breaker is not None:
            streams = StreamsBreakerImpl(StreamsValkeyImpl(valkey), breaker)
        seeds: SeedsInterface = SeedsNullImpl()
        if isinstance(machines, MachinesEc2Impl):
            seeds = machines
        elif settings.machines_backend == "lima":
            seeds = SeedsChannelImpl(machines, timedelta(seconds=settings.machine_timeout_seconds))
        return cls(streams, seeds)

    def describe(self) -> list[str]:
        return [self.streams.describe()]

    async def start(self) -> None:
        await self.streams.start()

    async def close(self) -> None:
        await self.streams.close()


class PlatformInfraRoot:
    """The platform's getters on an infra root that holds a `PlatformInfra`
    as `_platform_infra`."""

    _platform_infra: PlatformInfra

    def get_streams(self) -> StreamsInterface:
        return self._platform_infra.streams

    def get_seeds(self) -> SeedsInterface:
        return self._platform_infra.seeds
