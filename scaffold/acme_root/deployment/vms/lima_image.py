"""Builds the cloud pool's image on Lima: a VM from the Lima template
`ACME_VM_IMAGE` names, Docker inside it, the host program installed in
it from this checkout by `install.sh`, then stopped and kept under the name
given, from which every VM of the pool starts
(`ACME_CLOUD_POOL_IMAGE`). The image holds no secret: the pool hands each
VM its seed as it starts.

    uv run python deployment/vms/lima_image.py acme-vm-image

Run from the repository's root, with Lima installed and a hypervisor. The
name must not start with the VMs' prefix and `p`, which are the pool's
own names. A name that stands already is kept as it is."""

import asyncio
import io
import os
import sys
import tarfile
from datetime import timedelta
from pathlib import Path

from acme.infra.impl.settings import InfraSettings
from acme.infra.vms import VmSpec, VmState
from acme.infra.vms.lima import VmsLimaImpl

LEFT_OUT = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        ".local",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        ".terraform",
        ".env",
    }
)
"""What a build in the VM never needs, or must never see."""

SOURCE = "/tmp/acme-source"


def source_tarball(root: Path) -> bytes:
    """The checkout as a tarball, without what `LEFT_OUT` names."""

    def kept(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if LEFT_OUT & set(Path(info.name).parts):
            return None
        return info

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(root, arcname=".", filter=kept)
    return buffer.getvalue()


async def build(name: str, root: Path, settings: InfraSettings) -> None:
    timeout = timedelta(seconds=settings.vm_timeout_seconds)
    boot = timedelta(seconds=settings.vm_boot_timeout_seconds)
    vms = VmsLimaImpl(timeout, boot, encrypted=settings.vm_store_encrypted)
    missing = await vms.probe(name)
    if missing is not None:
        raise SystemExit(f"no VM runs here: {missing}")
    if await vms.state(name) is not VmState.ABSENT:
        print(f"{name} stands already")
        return
    await vms.launch(name, VmSpec(image=settings.vm_image, egress_open=True))
    try:
        steps = (
            (("sh", "-c", f"rm -rf {SOURCE} && mkdir -p {SOURCE} && tar -xz -C {SOURCE}"), True),
            (("sudo", "-n", "sh", f"{SOURCE}/deployment/vms/install.sh", SOURCE), False),
            (("rm", "-rf", SOURCE), False),
        )
        for argv, sends in steps:
            stdin = source_tarball(root) if sends else None
            reply = await vms.run(name, argv, bound=boot, stdin=stdin)
            if not reply.ok:
                raise SystemExit(
                    f"{argv[0]} failed in {name}: {reply.reason()}\n"
                    + reply.stdout.decode(errors="replace")[-2000:]
                )
        await vms.stop(name)
    except BaseException:
        await vms.destroy(name)
        raise
    print(f"{name} holds the host program; set ACME_CLOUD_POOL_IMAGE={name}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: lima_image.py <name>")
    asyncio.run(build(sys.argv[1], Path(os.getcwd()), InfraSettings()))


if __name__ == "__main__":
    main()
