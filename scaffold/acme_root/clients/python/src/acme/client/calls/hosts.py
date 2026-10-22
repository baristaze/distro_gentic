"""The hosts namespace's calls: a workspace host's own and a product
claimant's own. Each enrolls once with an enrollment token of its kind,
then calls with a credential of its own, which it rotates before it
ends. None of them is retried: an enrollment twice is two hosts or two
claimants, a credential rotated twice ends its holder, and a lost report
is the claimant's journal to send again (`acme.client.claimant`)."""

from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

from acme.client.calls.exec_relay import CONTROL_IDLE_SECONDS
from acme.client.transport import Transport
from acme.client.types.hosts import (
    AdvertisementBody,
    ClaimantClaimView,
    ClaimantControlView,
    ClaimantWorkView,
    ClaimView,
    HostView,
    IssuedClaimantCredentialView,
    IssuedHostCredentialView,
)


class HostsCalls(Transport):
    """A host's and a claimant's enrollment, credential, and claims."""

    async def enroll_host(
        self,
        enrollment_token: str,
        name: str,
        advertisement: AdvertisementBody,
        exec_version: int,
    ) -> IssuedHostCredentialView:
        """The host's own credential, in the clear once. The pool is the
        token's to say, never the host's."""
        answer = await self.request(
            "POST",
            "/v1/hosts/enrollments",
            json={
                "name": name,
                "advertisement": advertisement.model_dump(mode="json", exclude_none=True),
                "exec_version": exec_version,
            },
            token=enrollment_token,
        )
        return IssuedHostCredentialView.model_validate(answer)

    async def enroll_vm(
        self,
        key: str,
        name: str,
        advertisement: AdvertisementBody,
        exec_version: int,
    ) -> IssuedHostCredentialView:
        """The credential of a host that runs in a VM of the platform's
        cloud pool, traded once for the key the pool handed the VM. Its
        tenant, its pool, and its session are the platform's to say. A 409
        while the VM serves no session yet."""
        answer = await self.request(
            "POST",
            "/v1/hosts/vm-enrollments",
            json={
                "name": name,
                "advertisement": advertisement.model_dump(mode="json", exclude_none=True),
                "exec_version": exec_version,
            },
            token=key,
        )
        return IssuedHostCredentialView.model_validate(answer)

    async def rotate_host_credential(self) -> IssuedHostCredentialView:
        """The host's next credential; the one this client holds ends after
        a short grace."""
        answer = await self.request("POST", "/v1/hosts/me/credentials")
        return IssuedHostCredentialView.model_validate(answer)

    async def host_heartbeat(self, advertisement: AdvertisementBody, exec_version: int) -> HostView:
        answer = await self.request(
            "POST",
            "/v1/hosts/me/heartbeats",
            json={
                "advertisement": advertisement.model_dump(mode="json", exclude_none=True),
                "exec_version": exec_version,
            },
        )
        return HostView.model_validate(answer)

    async def claim_host_work(self, exec_version: int) -> ClaimView:
        """The next item pinned to this host or its pool, or none."""
        answer = await self.request(
            "POST", "/v1/hosts/me/claims", json={"exec_version": exec_version}
        )
        return ClaimView.model_validate(answer)

    async def enroll_claimant(
        self, enrollment_token: str, name: str
    ) -> IssuedClaimantCredentialView:
        """The claimant's own credential, in the clear once. Its kind and
        its pool are the token's to say, never the claimant's."""
        answer = await self.request(
            "POST", "/v1/claimants/enrollments", json={"name": name}, token=enrollment_token
        )
        return IssuedClaimantCredentialView.model_validate(answer)

    async def rotate_claimant_credential(self) -> IssuedClaimantCredentialView:
        """The claimant's next credential; the one this client holds ends
        after a short grace."""
        answer = await self.request("POST", "/v1/claimants/me/credentials")
        return IssuedClaimantCredentialView.model_validate(answer)

    async def claim_claimant_work(self) -> ClaimantClaimView:
        """The next item of the claimant's kind on the lanes its credential
        names, or none."""
        answer = await self.request("POST", "/v1/claimants/me/claims")
        return ClaimantClaimView.model_validate(answer)

    async def claimant_control_stream(
        self, items: Sequence[UUID] = ()
    ) -> AsyncIterator[ClaimantControlView]:
        """The claimant's control stream, opened from here and held open:
        each line as it arrives, until the platform ends it with the
        credential it was opened with. `items` are those it works on now,
        which the stream revokes at its first read once they are no longer
        its own. A line that does not come within `CONTROL_IDLE_SECONDS`
        takes the stream for lost."""
        params = {"item": [str(item) for item in items]} if items else {}
        path = "/v1/claimants/me/control"
        async for line in self.lines(path, params=params, idle_seconds=CONTROL_IDLE_SECONDS):
            yield ClaimantControlView.model_validate_json(line)

    async def extend_claimant_lease(self, item_id: UUID, claim_token: UUID) -> ClaimantWorkView:
        """Renews the lease on the item the claimant holds, under the claim
        token its claim was handed."""
        answer = await self.request(
            "POST",
            f"/v1/claimants/me/items/{item_id}/lease",
            json={"claim_token": str(claim_token)},
        )
        return ClaimantWorkView.model_validate(answer)

    async def report_claimant_work(self, item_id: UUID, body: dict[str, Any]) -> ClaimantWorkView:
        """The claimant's answer for the item it holds: its `claim_token`,
        its `outcome` (`done` or `failed`), and a failure's `error`."""
        answer = await self.request("POST", f"/v1/claimants/me/items/{item_id}/report", json=body)
        return ClaimantWorkView.model_validate(answer)
