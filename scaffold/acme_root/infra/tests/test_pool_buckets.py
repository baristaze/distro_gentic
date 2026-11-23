"""The buckets as a VM of the cloud pool reaches them. One store signs a
link a browser follows for the address a browser reaches it at, and a link
a VM's host follows for the address a VM reaches it at: on Lima, this
host's ports as `host.lima.internal`, since 127.0.0.1 in a guest is the
guest. Signing makes no request, so no store answers here."""

from datetime import timedelta
from typing import Any

import pytest

from acme.infra.base import new_id
from acme.infra.buckets import Buckets
from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings

TTL = timedelta(minutes=1)
BROWSER = "http://127.0.0.1:59000"
VM = "http://host.lima.internal:59000"


def configured(**settings: Any) -> InfraConfiguredImpl:
    """The infra root over one S3 store: the process reaches it inside its
    network, a browser at a host port."""
    return InfraConfiguredImpl(
        InfraSettings.model_validate(
            {
                "_env_file": None,
                "environment": "test",
                "buckets_backend": "s3",
                "s3_endpoint_url": "http://minio:9000",
                "s3_presign_endpoint_url": BROWSER,
                "s3_access_key": "acme",
                "s3_secret_key": "acme-minio-local",
                "s3_bucket_prefix": "t",
                **settings,
            }
        )
    )


async def test_one_store_signs_a_vms_link_for_the_vms_address_and_a_browsers_for_its_own() -> None:
    infra = configured(cloud_pool_s3_endpoint_url=VM)
    org = new_id()
    await infra.start()
    try:
        links = {
            where: (
                await store.presign_get(org, Buckets.SNAPSHOTS, "s/a.tar", TTL),
                await store.presign_part(org, Buckets.SNAPSHOTS, "s/a.tar", "u-1", 1, 10, TTL),
            )
            for where, store in ((BROWSER, infra.get_buckets()), (VM, infra.get_vm_buckets()))
        }
    finally:
        await infra.close()
    for where, signed in links.items():
        for link in signed:
            assert link.startswith(f"{where}/t-snapshots/{org}/s/a.tar?"), link


@pytest.mark.parametrize(
    "settings",
    [
        {"cloud_pool_s3_endpoint_url": ""},
        {"buckets_backend": "local", "cloud_pool_s3_endpoint_url": VM},
    ],
    ids=["no-address-of-its-own", "a-store-that-is-not-s3"],
)
def test_a_vm_follows_a_browsers_links_where_it_reaches_the_store_at_no_address_of_its_own(
    settings: dict[str, str],
) -> None:
    infra = configured(**settings)
    assert infra.get_vm_buckets() is infra.get_buckets()
