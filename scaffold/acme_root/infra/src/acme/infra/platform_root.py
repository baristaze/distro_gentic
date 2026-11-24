"""The platform's infra: the streams read live while they are written, how a
VM of the cloud pool is handed its seed and reaches the buckets, and the VMs
of the platform's cloud account. Each infra root builds it with one call, names it
once where it describes, starts, and closes its capabilities, and serves its
getters through `PlatformInfraRoot`. Its settings are
`platform_settings.PlatformInfraSettings`."""

from dataclasses import dataclass
from datetime import timedelta

import aioboto3

from acme.infra.breaker import Breaker
from acme.infra.buckets import BucketsInterface
from acme.infra.buckets.s3 import BucketsS3Impl
from acme.infra.impl.settings import InfraSettings
from acme.infra.impl.valkey import ValkeyConnection
from acme.infra.streams import StreamsInterface
from acme.infra.streams.breaker import StreamsBreakerImpl
from acme.infra.streams.memory import StreamsMemoryImpl
from acme.infra.streams.valkey import StreamsValkeyImpl
from acme.infra.vms import SeedsInterface, VmsInterface
from acme.infra.vms.ec2 import VmsEc2Impl
from acme.infra.vms.seeded import PLAIN_WRITE, SeedsChannelImpl, SeedsNullImpl


def unsafe_on_platform(settings: InfraSettings) -> str | None:
    """Why the platform refuses these settings at boot, or None: a VM
    workspace on the platform's cloud VMs, since a VM of the cloud
    takes no command from outside, and its host pulls."""
    if settings.agent_workspace_backend == "vm" and settings.vms_backend == "ec2":
        return (
            "ACME_AGENT_WORKSPACE_BACKEND=vm is refused with ACME_VMS_BACKEND=ec2: "
            "a VM of the cloud takes no command from outside, and its host pulls"
        )
    return None


def cloud_vms(settings: InfraSettings, aws: aioboto3.Session) -> VmsInterface | None:
    """The VMs of the platform's cloud account, when the settings name
    them; None for any other backend, which the root builds itself."""
    if settings.vms_backend != "ec2":
        return None
    return VmsEc2Impl(
        aws,
        region=settings.aws_region,
        timeout=timedelta(seconds=settings.aws_timeout_seconds),
        boot=timedelta(seconds=settings.vm_boot_timeout_seconds),
        template=settings.vm_launch_template,
        subnets=tuple(s for s in settings.vm_subnets.split(",") if s),
        closed=settings.vm_closed_group,
        open_=settings.vm_open_group,
        encrypted=settings.vm_store_encrypted,
        hibernates=settings.vm_hibernation,
    )


def pool_buckets(settings: InfraSettings, aws: aioboto3.Session) -> BucketsInterface | None:
    """The buckets as a VM of the cloud pool reaches them, when it reaches
    them at an address of its own: the root's S3 store, through a client
    whose links name that address. None when a VM follows a browser's
    links, as the root's own store signs them."""
    address = settings.cloud_pool_s3_endpoint_url
    if settings.buckets_backend != "s3" or not address:
        return None
    return BucketsS3Impl(
        aws,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.aws_region,
        bucket_prefix=settings.s3_bucket_prefix,
        timeout=timedelta(seconds=settings.aws_timeout_seconds),
        presign_endpoint_url=address,
    )


@dataclass(frozen=True)
class PlatformInfra:
    """The platform's capabilities over one root's: its streams, its seeds
    over the root's VMs, and the buckets as a VM of the cloud pool reaches
    them, when that is not as the root's own store signs (`pool_buckets`)."""

    streams: StreamsInterface
    seeds: SeedsInterface
    vm_buckets: BucketsInterface | None = None

    @classmethod
    def local(cls, vms: VmsInterface) -> PlatformInfra:
        """In this process: the memory streams, and seeds handed through the
        twin VMs' channel."""
        return cls(
            StreamsMemoryImpl(),
            SeedsChannelImpl(vms, timedelta(seconds=30), PLAIN_WRITE),
        )

    @classmethod
    def configured(
        cls,
        settings: InfraSettings,
        valkey: ValkeyConnection | None,
        breaker: Breaker | None,
        vms: VmsInterface,
        aws: aioboto3.Session,
    ) -> PlatformInfra:
        """As the settings pick them: the live streams follow the cache, behind
        the same breaker; a VM of the cloud is handed its seed as it
        starts, and one of Lima's through the hypervisor's channel; a VM
        reaches the buckets where `cloud_pool_s3_endpoint_url` says."""
        streams: StreamsInterface = StreamsMemoryImpl()
        if valkey is not None and breaker is not None:
            streams = StreamsBreakerImpl(StreamsValkeyImpl(valkey), breaker)
        seeds: SeedsInterface = SeedsNullImpl()
        if isinstance(vms, VmsEc2Impl):
            seeds = vms
        elif settings.vms_backend == "lima":
            seeds = SeedsChannelImpl(vms, timedelta(seconds=settings.vm_timeout_seconds))
        return cls(streams, seeds, pool_buckets(settings, aws))

    def describe(self) -> list[str]:
        return [self.streams.describe()]

    async def start(self) -> None:
        await self.streams.start()
        if self.vm_buckets is not None:
            await self.vm_buckets.start()

    async def close(self) -> None:
        if self.vm_buckets is not None:
            await self.vm_buckets.close()
        await self.streams.close()


class PlatformInfraRoot:
    """The platform's getters on an infra root that holds a `PlatformInfra`
    as `_platform_infra` and its own store as `_buckets`."""

    _platform_infra: PlatformInfra
    _buckets: BucketsInterface

    def get_streams(self) -> StreamsInterface:
        return self._platform_infra.streams

    def get_seeds(self) -> SeedsInterface:
        return self._platform_infra.seeds

    def get_vm_buckets(self) -> BucketsInterface:
        return self._platform_infra.vm_buckets or self._buckets
