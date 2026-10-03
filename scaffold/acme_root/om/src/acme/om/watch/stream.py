"""The stream service: where the parts of a step wait for whoever watches.
It implements the loop's stream sink, so an emit into it never waits, and
it holds a bounded buffer per open stream on the shared cache, which is all
the state it holds. The session runner hands it to the loop as its sink, and
the API's watch reads it, so a viewer reads a step from a process other than
the one that runs it.
A part is a cache whose loss costs nothing: the step it adds up to is the
record, so a buffer that drops a part, or is lost whole, loses no fact."""

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.agents.sink import StreamSinkInterface
from acme.om.watch.types.live import LiveStream, Seen


class StreamServiceInterface(StreamSinkInterface):
    @abstractmethod
    async def read(self, session_id: UUID, seen: Sequence[Seen]) -> tuple[LiveStream, ...]:
        """The session's open streams, each with the parts after the last
        `seen` names for it, or every part it still holds for a stream
        `seen` does not name. A late viewer reads the buffered tail. Only
        the session's own streams: the caller has checked the reader's
        right to it."""
        ...

    @abstractmethod
    async def flush(self) -> None:
        """Waits until what is queued now is written."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Writes what is still queued, then stops. A root closes it before
        its infra."""
        ...
