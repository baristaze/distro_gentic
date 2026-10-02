"""The stream service: where the parts the loop emits wait for whoever
watches. It is the loop's stream sink, so emission never waits on it, and
it holds a bounded buffer per open stream, which is all the state it holds.
A part is a cache whose loss costs nothing: the step it adds up to is the
record, so a buffer that drops a part, or is lost whole, loses no fact."""

from abc import abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.agents.sink import StreamSinkInterface
from acme.om.watch.types.live import LiveStream, Seen


class StreamServiceInterface(StreamSinkInterface):
    @abstractmethod
    def read(self, session_id: UUID, seen: Sequence[Seen]) -> tuple[LiveStream, ...]:
        """The session's open streams, each with the parts after the last
        `seen` names for it, or every part it still holds for a stream
        `seen` does not name. A late viewer reads the buffered tail. Only
        the session's own streams: the caller has checked the reader's
        right to it."""
        ...
