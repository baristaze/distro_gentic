"""Vms in the platform's cloud account: each VM an EC2 instance
started from the cloud pool's launch template, found by the tag that
carries the name its caller chose. Every VM boots the pool's image, named
by its AMI id, as the module's `image_id` is. No image or snapshot of a
VM's disk is ever made: a disk is sealed under no session's key, so
`snapshot` and `read` refuse, and the module's role is denied them
(ADR 2070).

Nothing here reaches into a VM. The cloud closes its egress at its
network, by the security group a start names: the closed group reaches the
gateway alone, and the open group adds the open egress a session's policy
chose. A VM holds no instance role, so its metadata endpoint has no
credential to hand out; its seed, the first-boot data a start hands it, is
read by the image at each boot, and the endpoint is closed once its host
has read it (`seal`). The platform never calls into a VM: what runs
there, its host pulls, so `run` and `channel` refuse."""

import asyncio
import random
import re
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import timedelta
from typing import Any

import aioboto3

from acme.infra.aws_clients import AwsClientHolder, client_config
from acme.infra.aws_errors import ClientError, error_code, translated
from acme.infra.exceptions import BackendFailed, InfraValidationFailed
from acme.infra.vms import (
    Channel,
    SeedsInterface,
    SnapshotNotFound,
    VmReply,
    VmsInterface,
    VmSpec,
    VmState,
)

TAG = "acme:vm"
"""The tag that carries a VM's name."""

LIVE = ("pending", "running", "stopping", "stopped")
"""An instance in any other state is gone, or going."""

REFUSED = "a VM of the cloud takes no command from outside: what runs there, its host pulls"

NO_IMAGE = "a VM of the cloud keeps no image of its disk: its session's files are kept sealed"

AMI_ID = re.compile(r"ami-[0-9a-f]{8,17}")
"""An image named by its id, as the pool's own image is."""


class VmsEc2Impl(VmsInterface, SeedsInterface):
    """Vms through the EC2 API, each call bounded by the client's
    timeout, and each wait for a state by `boot`. `template` is the launch
    template the cloud pool's module makes: the instance's default size, its
    encrypted disk under the pool's key, and no instance role. A start that
    names a machine type runs that type, which the module's role allows only
    from its size map. A VM
    starts in one of `subnets`, picked at each start, and in `closed` or
    `open`, the security group of its egress. `encrypted` declares the
    template's disks encrypted, which the module holds."""

    def __init__(
        self,
        session: aioboto3.Session,
        *,
        region: str,
        timeout: timedelta,
        boot: timedelta,
        template: str,
        subnets: tuple[str, ...],
        closed: str,
        open_: str,
        encrypted: bool,
        poll: timedelta = timedelta(seconds=5),
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        config = client_config(timeout)
        self._ec2 = AwsClientHolder(
            "ec2", lambda: session.client("ec2", region_name=region, config=config)
        )
        self._boot = boot
        self._template = template
        self._subnets = subnets
        self._closed = closed
        self._open = open_
        self._encrypted = encrypted
        self._poll = poll
        self._sleep = sleep

    async def probe(self, longest: str) -> str | None:
        if not (self._template and self._subnets and self._closed and self._open):
            return (
                "the cloud's VMs name no launch template, subnets, and security groups "
                "of the cloud pool's module"
            )
        try:
            with translated("ec2", "probe"):
                await self._ec2.client().describe_launch_templates(
                    LaunchTemplateIds=[self._template]
                )
        except Exception as error:
            return f"the launch template {self._template} cannot be read: {error}"
        return None

    def closes_egress(self) -> bool:
        return True

    def limits(self) -> frozenset[str]:
        # A VM is the size of its machine type (`VmSpec.machine_type`), else
        # the launch template's; it holds no other limit.
        return frozenset()

    def encrypted_at_rest(self) -> bool:
        return self._encrypted

    async def state(self, name: str) -> VmState:
        instance = await self._instance(name)
        if instance is None:
            return VmState.ABSENT
        if instance["State"]["Name"] in ("pending", "running"):
            return VmState.RUNNING
        return VmState.STOPPED

    async def launch(self, name: str, spec: VmSpec, snapshot: str | None = None) -> None:
        await self._launch(name, spec, snapshot, None)

    async def run(
        self,
        name: str,
        argv: Sequence[str],
        *,
        bound: timedelta,
        stdin: bytes | None = None,
    ) -> VmReply:
        return VmReply(126, b"", REFUSED.encode())

    def channel(self, name: str) -> Channel:
        raise InfraValidationFailed(REFUSED)

    async def stop(self, name: str) -> None:
        instance = await self._instance(name)
        if instance is None or instance["State"]["Name"] == "stopped":
            return
        with translated("ec2", "stop"):
            await self._ec2.client().stop_instances(InstanceIds=[instance["InstanceId"]])
        await self._until(name, "stopped")

    async def snapshot(self, name: str, to: str) -> str:
        raise InfraValidationFailed(NO_IMAGE)

    async def digest(self, snapshot: str) -> str | None:
        return None  # none is ever made

    async def read(self, snapshot: str) -> AsyncIterator[bytes]:
        raise InfraValidationFailed(NO_IMAGE)
        yield b""  # an async generator, as the interface reads

    async def names(self, prefix: str) -> list[str]:
        named = {_name_of(instance) for instance in await self._instances(prefix + "*")}
        return sorted(name for name in named if name.startswith(prefix))

    async def destroy(self, name: str) -> None:
        for instance in await self._instances(name):
            with translated("ec2", "destroy"):
                await self._ec2.client().terminate_instances(InstanceIds=[instance["InstanceId"]])

    def describe(self) -> str:
        return f"vms=ec2({self._template})"

    async def start(self) -> None:
        await self._ec2.open()

    async def close(self) -> None:
        await self._ec2.close()

    # Seeds: the VM's first-boot data, and the endpoint closed once read.

    async def launch_seeded(
        self, name: str, spec: VmSpec, snapshot: str | None, seed: bytes
    ) -> None:
        await self._launch(name, spec, snapshot, seed)

    async def seal(self, name: str) -> None:
        instance = await self._instance(name)
        if instance is None:
            return
        with translated("ec2", "seal"):
            await self._ec2.client().modify_instance_metadata_options(
                InstanceId=instance["InstanceId"], HttpEndpoint="disabled"
            )

    # The parts.

    async def _launch(
        self, name: str, spec: VmSpec, snapshot: str | None, seed: bytes | None
    ) -> None:
        """The VM under `name` running in the group of its egress, with
        `seed` as its first-boot data when given. One that stands is started
        again, stopped first when it runs and must be handed a seed or move
        to another group; one made here that fails part way is
        terminated."""
        group = self._open if spec.egress_open else self._closed
        instance = await self._instance(name)
        if instance is None:
            await self._make(name, spec, snapshot, seed, group)
            return
        groups = {g["GroupId"] for g in instance.get("SecurityGroups", [])}
        running = instance["State"]["Name"] in ("pending", "running")
        if running and seed is None and groups == {group}:
            return
        instance_id = instance["InstanceId"]
        if running:
            await self.stop(name)
        with translated("ec2", "launch"):
            client = self._ec2.client()
            await client.modify_instance_attribute(InstanceId=instance_id, Groups=[group])
            if seed is not None:
                await client.modify_instance_attribute(
                    InstanceId=instance_id, UserData={"Value": seed}
                )
                await client.modify_instance_metadata_options(
                    InstanceId=instance_id, HttpEndpoint="enabled"
                )
            await client.start_instances(InstanceIds=[instance_id])
        await self._until(name, "running")

    async def _make(
        self,
        name: str,
        spec: VmSpec,
        snapshot: str | None,
        seed: bytes | None,
        group: str,
    ) -> None:
        if snapshot is not None:
            image = await self._image_of(snapshot)
            if image is None or image.get("State") != "available":
                raise SnapshotNotFound(f"no image stands under {snapshot}")
            image_id = image["ImageId"]
        else:
            image_id = spec.image
        asked: dict[str, Any] = {
            "LaunchTemplate": {"LaunchTemplateId": self._template},
            "ImageId": image_id,
            "MinCount": 1,
            "MaxCount": 1,
            "SubnetId": random.choice(self._subnets),
            "SecurityGroupIds": [group],
            "MetadataOptions": {
                "HttpEndpoint": "enabled",
                "HttpTokens": "required",
                "HttpPutResponseHopLimit": 1,
            },
            "TagSpecifications": _tagged(name, "instance", "volume"),
        }
        if spec.machine_type is not None:
            # The size its caller asked, which the module's role allows by
            # type; none asked starts the template's.
            asked["InstanceType"] = spec.machine_type
        if seed is not None:
            # As it stands: botocore encodes a start's user data to base64
            # itself, so the VM reads the seed back whole.
            asked["UserData"] = seed
        try:
            with translated("ec2", "launch"):
                await self._ec2.client().run_instances(**asked)
            await self._until(name, "running")
        except BaseException:
            await self.destroy(name)
            raise

    async def _until(self, name: str, state: str) -> None:
        """Waits for the VM to reach `state`, within the boot bound."""
        waited = 0.0
        while True:
            instance = await self._instance(name)
            if instance is not None and instance["State"]["Name"] == state:
                return
            if waited >= self._boot.total_seconds():
                raise BackendFailed("ec2", "wait", f"{name} not {state} in time")
            await self._sleep(self._poll.total_seconds())
            waited += self._poll.total_seconds()

    async def _image_of(self, source: str) -> dict[str, Any] | None:
        """The image a new VM boots, the pool's own, by its AMI id. None
        when none stands, or `source` names no AMI: no other image is
        ever made."""
        if not AMI_ID.fullmatch(source):
            return None
        with translated("ec2", "describe"):
            try:
                page = await self._ec2.client().describe_images(ImageIds=[source])
            except ClientError as error:
                if error_code(error).startswith("InvalidAMIID"):
                    return None
                raise
        found = page.get("Images", [])
        return found[0] if found else None

    async def _instance(self, name: str) -> dict[str, Any] | None:
        found = await self._instances(name)
        return found[0] if found else None

    async def _instances(self, named: str) -> list[dict[str, Any]]:
        filters = [
            {"Name": f"tag:{TAG}", "Values": [named]},
            {"Name": "instance-state-name", "Values": list(LIVE)},
        ]
        found: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            asked: dict[str, Any] = {"Filters": filters}
            if token:
                asked["NextToken"] = token
            with translated("ec2", "describe"):
                page = await self._ec2.client().describe_instances(**asked)
            for reservation in page.get("Reservations", []):
                found.extend(reservation.get("Instances", []))
            token = page.get("NextToken")
            if not token:
                return found


def _tagged(name: str, *kinds: str) -> list[dict[str, Any]]:
    return [{"ResourceType": kind, "Tags": [{"Key": TAG, "Value": name}]} for kind in kinds]


def _name_of(resource: dict[str, Any]) -> str:
    for tag in resource.get("Tags", []):
        if tag.get("Key") == TAG:
            return str(tag.get("Value", ""))
    return ""
