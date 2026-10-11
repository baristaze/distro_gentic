"""The cloud's machines over a fake EC2 and EBS: a machine is an instance of
the cloud pool's launch template, in the security group of its egress, with
no instance role of its own to hand out; its seed is its first-boot data,
and its metadata endpoint is closed once sealed. A snapshot is an image of
the stopped instance, held to a digest of the ids that name its bytes, and
read back block by block. Nothing calls into a machine: `run` and `channel`
refuse."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from acme.infra.exceptions import InfraValidationFailed
from acme.infra.machines import MachineSpec, MachineState, SnapshotNotFound
from acme.infra.machines.ec2 import TAG, MachinesEc2Impl

TEMPLATE = "lt-0pool"
CLOSED, OPEN = "sg-closed", "sg-open"
AMI = "ami-0base"


class Ec2:
    """An account's instances and images, as the calls the impl makes see
    them, each call recorded by name."""

    def __init__(self) -> None:
        self.instances: dict[str, dict[str, Any]] = {}
        self.images: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.blocks: dict[str, list[bytes]] = {}

    def _record(self, name: str, request: dict[str, Any]) -> None:
        self.calls.append((name, request))

    async def describe_launch_templates(self, **request: Any) -> dict[str, Any]:
        self._record("describe_launch_templates", request)
        return {"LaunchTemplates": [{"LaunchTemplateId": TEMPLATE}]}

    async def run_instances(self, **request: Any) -> dict[str, Any]:
        self._record("run_instances", request)
        instance_id = f"i-{len(self.instances):04d}"
        tags = request["TagSpecifications"][0]["Tags"]
        self.instances[instance_id] = {
            "InstanceId": instance_id,
            "ImageId": request["ImageId"],
            "State": {"Name": "running"},
            "Tags": tags,
            "SecurityGroups": [{"GroupId": g} for g in request["SecurityGroupIds"]],
            "UserData": request.get("UserData"),
            "MetadataOptions": request["MetadataOptions"],
        }
        return {"Instances": [self.instances[instance_id]]}

    async def describe_instances(self, **request: Any) -> dict[str, Any]:
        named, states = _filters(request)
        found = [
            i
            for i in self.instances.values()
            if _matches(i, named) and i["State"]["Name"] in states
        ]
        return {"Reservations": [{"Instances": found}] if found else []}

    async def describe_images(self, **request: Any) -> dict[str, Any]:
        if "ImageIds" in request:
            found = [i for i in self.images.values() if i["ImageId"] in request["ImageIds"]]
            if not found:
                error = {"Error": {"Code": "InvalidAMIID.NotFound", "Message": "no such image"}}
                raise ClientError(error, "DescribeImages")  # type: ignore[arg-type]
            return {"Images": found}
        named, _ = _filters(request)
        return {"Images": [i for i in self.images.values() if _matches(i, named)]}

    async def stop_instances(self, **request: Any) -> dict[str, Any]:
        self._record("stop_instances", request)
        for instance_id in request["InstanceIds"]:
            self.instances[instance_id]["State"]["Name"] = "stopped"
        return {}

    async def start_instances(self, **request: Any) -> dict[str, Any]:
        self._record("start_instances", request)
        for instance_id in request["InstanceIds"]:
            self.instances[instance_id]["State"]["Name"] = "running"
        return {}

    async def terminate_instances(self, **request: Any) -> dict[str, Any]:
        self._record("terminate_instances", request)
        for instance_id in request["InstanceIds"]:
            self.instances[instance_id]["State"]["Name"] = "terminated"
        return {}

    async def modify_instance_attribute(self, **request: Any) -> dict[str, Any]:
        self._record("modify_instance_attribute", request)
        instance = self.instances[request["InstanceId"]]
        if "Groups" in request:
            instance["SecurityGroups"] = [{"GroupId": g} for g in request["Groups"]]
        if "UserData" in request:
            instance["UserData"] = request["UserData"]["Value"]
        return {}

    async def modify_instance_metadata_options(self, **request: Any) -> dict[str, Any]:
        self._record("modify_instance_metadata_options", request)
        self.instances[request["InstanceId"]]["MetadataOptions"]["HttpEndpoint"] = request[
            "HttpEndpoint"
        ]
        return {}

    async def create_image(self, **request: Any) -> dict[str, Any]:
        self._record("create_image", request)
        image_id = f"ami-{len(self.images):04d}"
        snapshot_id = f"snap-{len(self.images):04d}"
        self.images[image_id] = {
            "ImageId": image_id,
            "State": "available",
            "Tags": request["TagSpecifications"][0]["Tags"],
            "BlockDeviceMappings": [{"Ebs": {"SnapshotId": snapshot_id}}],
        }
        self.blocks[snapshot_id] = [b"disk-block-0", b"disk-block-1"]
        return {"ImageId": image_id}

    async def deregister_image(self, **request: Any) -> dict[str, Any]:
        self._record("deregister_image", request)
        self.images.pop(request["ImageId"])
        return {}

    async def delete_snapshot(self, **request: Any) -> dict[str, Any]:
        self._record("delete_snapshot", request)
        self.blocks.pop(request["SnapshotId"], None)
        return {}

    async def list_snapshot_blocks(self, **request: Any) -> dict[str, Any]:
        blocks = self.blocks[request["SnapshotId"]]
        return {"Blocks": [{"BlockIndex": i, "BlockToken": f"t{i}"} for i in range(len(blocks))]}

    async def get_snapshot_block(self, **request: Any) -> dict[str, Any]:
        data = self.blocks[request["SnapshotId"]][request["BlockIndex"]]
        return {"BlockData": Body(data)}


class Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


def _filters(request: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    named, states = "", ("pending", "running", "stopping", "stopped")
    for item in request.get("Filters", []):
        if item["Name"] == f"tag:{TAG}":
            (named,) = item["Values"]
        if item["Name"] == "instance-state-name":
            states = tuple(item["Values"])
    return named, states


def _matches(resource: dict[str, Any], named: str) -> bool:
    value = next((t["Value"] for t in resource["Tags"] if t["Key"] == TAG), None)
    if value is None:
        return False  # an image of the account's own, such as the pool's
    return value.startswith(named[:-1]) if named.endswith("*") else value == named


class Session:
    def __init__(self, ec2: Ec2) -> None:
        self.ec2 = ec2

    def client(self, service: str, **_: Any) -> Any:
        @asynccontextmanager
        async def opened() -> AsyncIterator[Ec2]:
            yield self.ec2

        return opened()


async def no_wait(_: float) -> None:
    return None


@pytest.fixture
async def cloud() -> AsyncIterator[tuple[MachinesEc2Impl, Ec2]]:
    ec2 = Ec2()
    machines = MachinesEc2Impl(
        Session(ec2),  # type: ignore[arg-type]
        region="eu-west-1",
        timeout=timedelta(seconds=10),
        boot=timedelta(seconds=30),
        template=TEMPLATE,
        subnets=("subnet-0a", "subnet-0b"),
        closed=CLOSED,
        open_=OPEN,
        encrypted=True,
        sleep=no_wait,
    )
    await machines.start()
    yield machines, ec2
    await machines.close()


def spec(*, egress_open: bool = False) -> MachineSpec:
    return MachineSpec(image=AMI, egress_open=egress_open)


async def test_a_machine_starts_from_the_pools_template_in_its_egress_group_with_its_seed(
    cloud: tuple[MachinesEc2Impl, Ec2],
) -> None:
    machines, ec2 = cloud
    assert await machines.probe("acme-vm-p0123") is None
    assert machines.closes_egress() and machines.limits() == frozenset()
    await machines.launch_seeded("acme-vm-pclosed", spec(), None, b'{"key":"hmk_x"}')
    await machines.launch("acme-vm-popen", spec(egress_open=True))
    runs = [request for name, request in ec2.calls if name == "run_instances"]
    closed, opened = runs
    assert closed["LaunchTemplate"] == {"LaunchTemplateId": TEMPLATE}
    assert closed["SecurityGroupIds"] == [CLOSED] and opened["SecurityGroupIds"] == [OPEN]
    assert {closed["SubnetId"], opened["SubnetId"]} <= {"subnet-0a", "subnet-0b"}
    assert closed["UserData"] == b'{"key":"hmk_x"}', "as it stands: botocore encodes it once"
    assert "UserData" not in opened
    assert closed["MetadataOptions"]["HttpTokens"] == "required"
    assert "IamInstanceProfile" not in closed, "a machine holds no role to hand out"
    assert await machines.state("acme-vm-pclosed") is MachineState.RUNNING
    assert await machines.state("acme-vm-pnone") is MachineState.ABSENT

    await machines.seal("acme-vm-pclosed")
    (instance,) = [i for i in ec2.instances.values() if i["SecurityGroups"][0]["GroupId"] == CLOSED]
    assert instance["MetadataOptions"]["HttpEndpoint"] == "disabled"


async def test_a_new_machine_boots_the_pools_image_named_by_its_ami_id(
    cloud: tuple[MachinesEc2Impl, Ec2],
) -> None:
    machines, ec2 = cloud
    pools = "ami-0123456789abcdef0"
    ec2.images[pools] = {"ImageId": pools, "State": "available", "Tags": []}
    await machines.launch_seeded("acme-vm-pa", spec(), pools, b"seed")
    (run,) = [request for name, request in ec2.calls if name == "run_instances"]
    assert run["ImageId"] == pools, "the module's image_id, as the operator gives it"
    assert await machines.names("acme-vm-p") == ["acme-vm-pa"], "the image is no name of the pool's"
    with pytest.raises(SnapshotNotFound):
        await machines.launch_seeded("acme-vm-pb", spec(), "ami-0fffffffffffffff0", b"seed")
    assert await machines.state("acme-vm-pb") is MachineState.ABSENT


async def test_a_running_machine_handed_a_new_seed_is_stopped_reseeded_and_started(
    cloud: tuple[MachinesEc2Impl, Ec2],
) -> None:
    machines, ec2 = cloud
    await machines.launch_seeded("acme-vm-pa", spec(), None, b"first")
    await machines.seal("acme-vm-pa")
    await machines.launch_seeded("acme-vm-pa", spec(), None, b"second")
    (instance,) = ec2.instances.values()
    assert instance["UserData"] == b"second"
    assert instance["MetadataOptions"]["HttpEndpoint"] == "enabled", "open again to read it"
    assert instance["State"]["Name"] == "running"
    names = [name for name, _ in ec2.calls]
    assert names.index("stop_instances") < names.index("start_instances")


async def test_a_snapshot_is_an_image_of_the_stopped_disk_held_to_its_digest_and_read_back(
    cloud: tuple[MachinesEc2Impl, Ec2],
) -> None:
    machines, ec2 = cloud
    await machines.launch("acme-vm-pa", spec())
    with pytest.raises(SnapshotNotFound):
        await machines.snapshot("acme-vm-pa", "acme-vm-pxx-0001")  # still running
    await machines.stop("acme-vm-pa")
    digest = await machines.snapshot("acme-vm-pa", "acme-vm-pxx-0001")
    assert digest.startswith("sha256:") and len(digest) == len("sha256:") + 64
    assert await machines.digest("acme-vm-pxx-0001") == digest
    assert await machines.snapshot("acme-vm-pa", "acme-vm-pxx-0001") == digest, "kept as it is"
    assert [part async for part in machines.read("acme-vm-pxx-0001")] == [
        b"disk-block-0",
        b"disk-block-1",
    ]
    await machines.destroy("acme-vm-pa")
    await machines.launch("acme-vm-pb", spec(), "acme-vm-pxx-0001")
    _, restored = [r for n, r in ec2.calls if n == "run_instances"]
    assert restored["ImageId"] != AMI, "started from the snapshot's image"
    assert sorted(await machines.names("acme-vm-p")) == ["acme-vm-pb", "acme-vm-pxx-0001"]

    await machines.destroy("acme-vm-pxx-0001")
    assert await machines.digest("acme-vm-pxx-0001") is None
    assert ("delete_snapshot", {"SnapshotId": "snap-0000"}) in ec2.calls
    with pytest.raises(SnapshotNotFound):
        await machines.launch("acme-vm-pc", spec(), "acme-vm-pxx-0001")


async def test_nothing_calls_into_a_machine(cloud: tuple[MachinesEc2Impl, Ec2]) -> None:
    machines, _ = cloud
    await machines.launch("acme-vm-pa", spec())
    reply = await machines.run("acme-vm-pa", ("true",), bound=timedelta(seconds=1))
    assert not reply.ok and "pulls" in reply.reason()
    with pytest.raises(InfraValidationFailed):
        machines.channel("acme-vm-pa")


async def test_a_probe_names_the_template_and_groups_it_misses() -> None:
    machines = MachinesEc2Impl(
        Session(Ec2()),  # type: ignore[arg-type]
        region="eu-west-1",
        timeout=timedelta(seconds=10),
        boot=timedelta(seconds=30),
        template="",
        subnets=(),
        closed="",
        open_="",
        encrypted=True,
    )
    assert "launch template" in str(await machines.probe("acme-vm-p0"))
