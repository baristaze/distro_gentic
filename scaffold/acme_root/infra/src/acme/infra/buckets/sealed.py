"""An object sealed under a key of its own, the form a file takes while it
crosses between the platform and a host: whoever holds the key reads the
one object it seals, and nothing else.

The object is a run of frames. Each frame seals a slice of the file with
AES-GCM under the object's key, a nonce of its own at its head, and is
bound to the object's reference, its place, and whether it is the last,
so a frame moved, dropped, or taken from another object opens nothing.
Every frame but the last is `FRAME_BYTES` sealed, a whole MiB, so each part
of the store's plan of the sealed size (`part_sizes`, whole MiB but the
last) holds whole frames: a part sealed again on a resume, with fresh
nonces, stands beside the parts the store kept. A file of no bytes is one
empty frame.

What a frame opens to is checked again whole, against the size and the
digest its item declares, before anything uses it."""

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from acme.infra.buckets import MIB, part_sizes
from acme.infra.exceptions import InfraValidationFailed

KEY_BYTES = 32
"""An object's key: AES-256."""
NONCE_BYTES = 12
TAG_BYTES = 16
FRAME_BYTES = MIB
"""What every frame but the last takes in the store."""
SEAL_BYTES = NONCE_BYTES + TAG_BYTES
"""What sealing adds to each frame."""
FRAME_PLAIN = FRAME_BYTES - SEAL_BYTES
"""The bytes of the file one full frame holds."""
DIGEST_SCHEME = "sha256:"


class ObjectRefused(InfraValidationFailed):
    """An object that is not what its item declares: a frame that does not
    open under its key at its place, a length other than its size seals
    to, or bytes whose digest differs. Nothing of it is used."""

    code = "object_refused"


def new_key() -> bytes:
    return os.urandom(KEY_BYTES)


def digest_of(data: bytes) -> str:
    return DIGEST_SCHEME + hashlib.sha256(data).hexdigest()


def frame_count(size: int) -> int:
    """How many frames an object of `size` bytes of its file holds."""
    if size < 0:
        raise ValueError(f"a file is no fewer than 0 bytes, not {size}")
    return max(1, -(-size // FRAME_PLAIN))


def sealed_size(size: int) -> int:
    """What an object of `size` bytes of its file takes in the store."""
    return size + SEAL_BYTES * frame_count(size)


def _bound(reference: str, index: int, last: bool) -> bytes:
    return reference.encode() + b"\x00" + index.to_bytes(8, "big") + (b"\x01" if last else b"\x00")


def seal_frame(key: bytes, reference: str, index: int, last: bool, plain: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plain, _bound(reference, index, last))


def open_frame(key: bytes, reference: str, index: int, last: bool, sealed: bytes) -> bytes:
    if len(sealed) < SEAL_BYTES:
        raise ObjectRefused(f"frame {index} of {reference} is cut short")
    nonce = sealed[:NONCE_BYTES]
    try:
        return AESGCM(key).decrypt(nonce, sealed[NONCE_BYTES:], _bound(reference, index, last))
    except InvalidTag:
        raise ObjectRefused(f"frame {index} of {reference} does not open under its key") from None


@dataclass(frozen=True)
class SealedPart:
    """One part of the upload of a sealed object: its number and its length
    in the store's plan, where it starts there, and the frames and the
    slice of the file it seals."""

    number: int
    offset: int
    size_bytes: int
    first_frame: int
    frames: int
    plain_offset: int
    plain_size: int


def sealed_parts(size: int) -> tuple[SealedPart, ...]:
    """The parts of the upload of an object of `size` bytes of its file, in
    order: the store's plan of its sealed size, each part whole frames."""
    total = sealed_size(size)
    parts: list[SealedPart] = []
    offset = 0
    for number, length in enumerate(part_sizes(total), 1):
        first = offset // FRAME_BYTES
        frames = -(-length // FRAME_BYTES)
        plain_offset = first * FRAME_PLAIN
        plain_size = min(size, (first + frames) * FRAME_PLAIN) - plain_offset
        parts.append(SealedPart(number, offset, length, first, frames, plain_offset, plain_size))
        offset += length
    return tuple(parts)


def frame_slices(size: int, first: int, frames: int) -> Iterator[tuple[int, bool, int, int]]:
    """Each frame from `first`, `frames` of them, of an object of `size`
    bytes: its place, whether it is the last, and the offset and length of
    the slice of the file it seals."""
    count = frame_count(size)
    for index in range(first, min(first + frames, count)):
        start = index * FRAME_PLAIN
        yield index, index == count - 1, start, min(size, start + FRAME_PLAIN) - start


def seal_object(key: bytes, reference: str, data: bytes) -> bytes:
    """A whole file sealed: what a service `put`s."""
    return _sealed(key, reference, data, 0, frame_count(len(data)))


def seal_part(key: bytes, reference: str, data: bytes, part: SealedPart) -> bytes:
    """One part of the upload of a file held whole in memory, sealed."""
    return _sealed(key, reference, data, part.first_frame, part.frames)


def _sealed(key: bytes, reference: str, data: bytes, first: int, frames: int) -> bytes:
    view = memoryview(data)
    return b"".join(
        seal_frame(key, reference, index, last, bytes(view[start : start + length]))
        for index, last, start, length in frame_slices(len(data), first, frames)
    )


def open_object(key: bytes, reference: str, size: int, digest: str, sealed: bytes) -> bytes:
    """The file a whole sealed object holds, once it opens to `size` bytes
    whose digest is `digest`; `ObjectRefused` otherwise."""
    opener = Opener(key, reference, size)
    data = b"".join(opener.feed(sealed))
    opener.close()
    if digest_of(data) != digest:
        raise ObjectRefused(f"{reference} does not match its digest")
    return data


class Opener:
    """Opens a sealed object as its bytes arrive, in any chunks: `feed`
    answers the file's bytes of each frame it completes, and `close`
    refuses an object that ended short. Bytes past what `size` seals to
    are refused as they arrive, so a store that sends more is read no
    further."""

    def __init__(self, key: bytes, reference: str, size: int) -> None:
        self._key = key
        self._reference = reference
        self._size = size
        self._count = frame_count(size)
        self._next = 0
        self._held = bytearray()
        self.received = 0

    def _length(self, index: int) -> int:
        if index < self._count - 1:
            return FRAME_BYTES
        return self._size - index * FRAME_PLAIN + SEAL_BYTES

    def feed(self, chunk: bytes) -> list[bytes]:
        self.received += len(chunk)
        if self.received > sealed_size(self._size):
            raise ObjectRefused(f"{self._reference} is longer than {self._size} bytes seal to")
        self._held += chunk
        opened: list[bytes] = []
        while self._next < self._count and len(self._held) >= self._length(self._next):
            length = self._length(self._next)
            frame = bytes(self._held[:length])
            del self._held[:length]
            last = self._next == self._count - 1
            opened.append(open_frame(self._key, self._reference, self._next, last, frame))
            self._next += 1
        return opened

    def close(self) -> None:
        if self._next < self._count or self._held:
            raise ObjectRefused(f"{self._reference} ended short of {self._size} bytes")
