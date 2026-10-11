"""Machines in the platform's cloud account: each machine an EC2 instance
started from the cloud pool's launch template, each snapshot an image of a
stopped instance, its disk kept by the cloud's own snapshots under the
template's key. A machine and a snapshot are found by the tag that carries
the name their caller chose.

Nothing here reaches into a machine. The cloud closes its egress at its
network, by the security group a start names: the closed group reaches the
gateway alone, and the open group adds the open egress a session's policy
chose. A machine holds no instance role, so its metadata endpoint has no
credential to hand out; its seed, the first-boot data a start hands it, is
read by the image at each boot, and the endpoint is closed once its host
has read it (`seal`). The platform never calls into a machine: what runs
there, its host pulls, so `run` and `channel` refuse."""

import asyncio
import base64
import hashlib
import random
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import timedelta
from typing import Any

import aioboto3

from acme.infra.aws_clients import AwsClientHolder, client_config
from acme.infra.aws_errors import translated
from acme.infra.exceptions import BackendFailed, InfraValidationFailed
from acme.infra.machines import (
    Channel,
    MachineReply,
    MachinesInterface,
    MachineSpec,
    MachineState,
    SeedsInterface,
    SnapshotNotFound,
)

TAG = "acme:machine"
"""The tag that carries a machine's name, or a snapshot's."""

LIVE = ("pending", "running", "stopping", "stopped")
"""An instance in any other state is gone, or going."""

REFUSED = "a machine of the cloud takes no command from outside: what runs there, its host pulls"


class MachinesEc2Impl(MachinesInterface, SeedsInterface):
    """Machines through the EC2 API, each call bounded by the client's
    timeout, and each wait for a state by `boot`. `template` is the launch
    template the cloud pool's module makes: the instance's size, its
    encrypted disk under the pool's key, and no instance role. A machine
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
        self._ebs = AwsClientHolder(
            "ebs", lambda: session.client("ebs", region_name=region, config=config)
        )
        self._region = region
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
                "the cloud's machines name no launch template, subnets, and security groups "
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
        # A machine is the launch template's size; it holds no other limit.
        return frozenset()

    def encrypted_at_rest(self) -> bool:
        return self._encrypted

    async def state(self, name: str) -> MachineState:
        instance = await self._instance(name)
        if instance is not None:
            if instance["State"]["Name"] in ("pending", "running"):
                return MachineState.RUNNING
            return MachineState.STOPPED
        if await self._image(name) is not None:
            return MachineState.STOPPED
        return MachineState.ABSENT

    async def launch(self, name: str, spec: MachineSpec, snapshot: str | None = None) -> None:
        await self._launch(name, spec, snapshot, None)

    async def run(
        self,
        name: str,
        argv: Sequence[str],
        *,
        bound: timedelta,
        stdin: bytes | None = None,
    ) -> MachineReply:
        return MachineReply(126, b"", REFUSED.encode())

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
        if await self._image(to) is None:
            instance = await self._instance(name)
            source = None if instance is not None else await self._image(name)
            if instance is not None and instance["State"]["Name"] == "stopped":
                with translated("ec2", "snapshot"):
                    await self._ec2.client().create_image(
                        InstanceId=instance["InstanceId"],
                        Name=to,
                        NoReboot=True,
                        TagSpecifications=_tagged(to, "image", "snapshot"),
                    )
            elif source is not None:
                with translated("ec2", "snapshot"):
                    await self._ec2.client().copy_image(
                        SourceImageId=source["ImageId"],
                        SourceRegion=self._region,
                        Name=to,
                        Encrypted=self._encrypted,
                        TagSpecifications=_tagged(to, "image"),
                    )
            else:
                raise SnapshotNotFound(f"nothing stopped stands under {name}")
            await self._available(to)
        digest = await self.digest(to)
        if digest is None:
            raise SnapshotNotFound(f"no snapshot stands under {to}")
        return digest

    async def digest(self, snapshot: str) -> str | None:
        image = await self._image(snapshot)
        if image is None:
            return None
        # A snapshot of the cloud's never changes once taken, so the ids of
        # the image and of each disk it holds name its bytes: one replaced
        # under the same name answers another digest.
        disks = sorted(_snapshot_ids(image))
        named = f"{image['ImageId']}:{','.join(disks)}"
        return "sha256:" + hashlib.sha256(named.encode()).hexdigest()

    async def read(self, snapshot: str) -> AsyncIterator[bytes]:
        image = await self._image(snapshot)
        if image is None or image.get("State") != "available":
            raise SnapshotNotFound(f"no snapshot stands under {snapshot}")
        for disk in sorted(_snapshot_ids(image)):
            token: str | None = None
            while True:
                asked: dict[str, Any] = {"SnapshotId": disk}
                if token:
                    asked["NextToken"] = token
                with translated("ebs", "read"):
                    listed = await self._ebs.client().list_snapshot_blocks(**asked)
                for block in listed.get("Blocks", []):
                    with translated("ebs", "read"):
                        got = await self._ebs.client().get_snapshot_block(
                            SnapshotId=disk,
                            BlockIndex=block["BlockIndex"],
                            BlockToken=block["BlockToken"],
                        )
                        yield await got["BlockData"].read()
                token = listed.get("NextToken")
                if not token:
                    break

    async def names(self, prefix: str) -> list[str]:
        named: set[str] = set()
        for instance in await self._instances(prefix + "*"):
            named.add(_name_of(instance))
        for image in await self._images(prefix + "*"):
            named.add(_name_of(image))
        return sorted(name for name in named if name.startswith(prefix))

    async def destroy(self, name: str) -> None:
        for instance in await self._instances(name):
            with translated("ec2", "destroy"):
                await self._ec2.client().terminate_instances(InstanceIds=[instance["InstanceId"]])
        for image in await self._images(name):
            with translated("ec2", "destroy"):
                await self._ec2.client().deregister_image(ImageId=image["ImageId"])
                for disk in _snapshot_ids(image):
                    await self._ec2.client().delete_snapshot(SnapshotId=disk)

    def describe(self) -> str:
        return f"machines=ec2({self._template})"

    async def start(self) -> None:
        await self._ec2.open()
        await self._ebs.open()

    async def close(self) -> None:
        await self._ebs.close()
        await self._ec2.close()

    # Seeds: the machine's first-boot data, and the endpoint closed once read.

    async def launch_seeded(
        self, name: str, spec: MachineSpec, snapshot: str | None, seed: bytes
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
        self, name: str, spec: MachineSpec, snapshot: str | None, seed: bytes | None
    ) -> None:
        """The machine under `name` running in the group of its egress, with
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
        spec: MachineSpec,
        snapshot: str | None,
        seed: bytes | None,
        group: str,
    ) -> None:
        if snapshot is not None:
            image = await self._image(snapshot)
            if image is None or image.get("State") != "available":
                raise SnapshotNotFound(f"no snapshot stands under {snapshot}")
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
        if seed is not None:
            asked["UserData"] = base64.b64encode(seed).decode()
        try:
            with translated("ec2", "launch"):
                await self._ec2.client().run_instances(**asked)
            await self._until(name, "running")
        except BaseException:
            await self.destroy(name)
            raise

    async def _until(self, name: str, state: str) -> None:
        """Waits for the machine to reach `state`, within the boot bound."""
        waited = 0.0
        while True:
            instance = await self._instance(name)
            if instance is not None and instance["State"]["Name"] == state:
                return
            if waited >= self._boot.total_seconds():
                raise BackendFailed("ec2", "wait", f"{name} not {state} in time")
            await self._sleep(self._poll.total_seconds())
            waited += self._poll.total_seconds()

    async def _available(self, name: str) -> None:
        """Waits for the image under `name` to be whole, within the boot
        bound."""
        waited = 0.0
        while True:
            image = await self._image(name)
            if image is not None and image.get("State") == "available":
                return
            if image is not None and image.get("State") == "failed":
                raise BackendFailed("ec2", "snapshot", f"{name} failed")
            if waited >= self._boot.total_seconds():
                raise BackendFailed("ec2", "snapshot", f"{name} not available in time")
            await self._sleep(self._poll.total_seconds())
            waited += self._poll.total_seconds()

    async def _instance(self, name: str) -> dict[str, Any] | None:
        found = await self._instances(name)
        return found[0] if found else None

    async def _image(self, name: str) -> dict[str, Any] | None:
        found = await self._images(name)
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

    async def _images(self, named: str) -> list[dict[str, Any]]:
        with translated("ec2", "describe"):
            page = await self._ec2.client().describe_images(
                Owners=["self"], Filters=[{"Name": f"tag:{TAG}", "Values": [named]}]
            )
        return [image for image in page.get("Images", []) if image.get("State") != "deregistered"]


def _tagged(name: str, *kinds: str) -> list[dict[str, Any]]:
    return [{"ResourceType": kind, "Tags": [{"Key": TAG, "Value": name}]} for kind in kinds]


def _name_of(resource: dict[str, Any]) -> str:
    for tag in resource.get("Tags", []):
        if tag.get("Key") == TAG:
            return str(tag.get("Value", ""))
    return ""


def _snapshot_ids(image: dict[str, Any]) -> list[str]:
    return [
        mapping["Ebs"]["SnapshotId"]
        for mapping in image.get("BlockDeviceMappings", [])
        if "Ebs" in mapping and mapping["Ebs"].get("SnapshotId")
    ]
