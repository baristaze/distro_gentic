"""The exec_relay namespace's calls: the exec work a host holds, and its
control stream. Each push carries the bytes as they cross, in base64,
and the hash the host declares of them, which the platform checks before
it reads them. None is retried here: the host decides what a lost answer
means for the item it holds."""

import base64
import hashlib
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

from acme.client.transport import Transport
from acme.client.types.exec_relay import (
    ControlView,
    ExecDetailView,
    ExecLeaseView,
    OutputStream,
    PreparedView,
)
from acme.client.types.retention import CrossingKind

CONTROL_IDLE_SECONDS = 60.0
"""How long a host's control stream waits for a line before it is taken for
lost and opened again: the platform pings well within it."""


def _declared(kind: CrossingKind, data: bytes) -> dict[str, Any]:
    """What a sender declares of the bytes it sends across the wall."""
    return {"kind": kind.value, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


class ExecRelayCalls(Transport):
    """A host's exec items, its workspace answers, and its control stream."""

    async def exec_detail(self, item_id: UUID) -> ExecDetailView:
        """What the host runs for an item it holds, opened."""
        answer = await self.request("GET", f"/v1/hosts/me/exec/{item_id}")
        return ExecDetailView.model_validate(answer)

    async def push_exec_parts(
        self, item_id: UUID, parts: Sequence[tuple[int, OutputStream, bytes]]
    ) -> None:
        """The parts of the item's output one flush window gathered, each by
        its place and its stream, in one push; one sent again lands once."""
        await self.request(
            "POST",
            f"/v1/hosts/me/exec/{item_id}/parts",
            json={
                "parts": [
                    {
                        "seq": seq,
                        "stream": stream.value,
                        "data": base64.b64encode(data).decode(),
                        "crossing": _declared(CrossingKind.stream_part, data),
                    }
                    for seq, stream, data in parts
                ]
            },
        )

    async def push_exec_result(self, item_id: UUID, data: bytes) -> None:
        """How the item ended: the first settlement wins, and a result for
        an item already settled is refused."""
        await self.request(
            "POST",
            f"/v1/hosts/me/exec/{item_id}/result",
            json={
                "data": base64.b64encode(data).decode(),
                "crossing": _declared(CrossingKind.result, data),
            },
        )

    async def extend_exec_lease(self, item_id: UUID) -> ExecLeaseView:
        answer = await self.request("POST", f"/v1/hosts/me/exec/{item_id}/lease")
        return ExecLeaseView.model_validate(answer)

    async def control_stream(self, after: UUID | None = None) -> AsyncIterator[ControlView]:
        """The host's control stream, opened from here and held open: each
        line as it arrives, until the platform ends it with the credential it
        was opened with. A line that does not come within
        `CONTROL_IDLE_SECONDS` takes the stream for lost."""
        params = {} if after is None else {"after": str(after)}
        path = "/v1/hosts/me/control"
        async for line in self.lines(path, params=params, idle_seconds=CONTROL_IDLE_SECONDS):
            yield ControlView.model_validate_json(line)

    async def answer_prepare(
        self,
        item_id: UUID,
        *,
        location: str | None = None,
        refused: str | None = None,
        lost: bool = False,
        unbuilt: bool = False,
    ) -> PreparedView:
        """A prepare this host claimed: where the workspace it made is, or why
        it made none, `lost` when the snapshot it was to start from is gone
        from its store or altered there, and `unbuilt` when the base it was
        to start from failed to build here. `held` False says another host
        of the pool holds the session's workspace, and this host lets its
        own go."""
        body: dict[str, object] = (
            {"location": location}
            if refused is None
            else {"refused": refused, "lost": lost, "unbuilt": unbuilt}
        )
        answer = await self.request("POST", f"/v1/hosts/me/workspaces/{item_id}", json=body)
        return PreparedView.model_validate(answer)

    async def answer_release(self, item_id: UUID) -> None:
        """A release, a purge, or an erase this host claimed: what it names is
        gone. A release keeps the workspace's files; a purge keeps none."""
        await self.request("POST", f"/v1/hosts/me/workspaces/{item_id}/released")

    async def answer_snapshot(
        self,
        item_id: UUID,
        *,
        reference: str | None = None,
        digest: str | None = None,
        size: int | None = None,
        refused: str | None = None,
    ) -> None:
        """A snapshot this host claimed: kept in its own store, by the
        reference the store knows it by, the SHA-256 of its bytes, and their
        size, never the bytes; or why it kept none."""
        body: dict[str, object] = (
            {"reference": reference, "digest": digest, "size": size}
            if refused is None
            else {"refused": refused}
        )
        await self.request("POST", f"/v1/hosts/me/workspaces/{item_id}/snapshot", json=body)
