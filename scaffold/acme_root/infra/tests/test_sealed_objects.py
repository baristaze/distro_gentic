"""An object sealed under a key of its own: its frames line up with the parts
of the store's plan, so a part sealed alone stands beside the others, and
it opens only whole, in order, under its key and its reference, to the
size and the digest it was declared with. Anything else is refused."""

import os

import pytest

from acme.infra.buckets import MIB, part_sizes
from acme.infra.buckets.sealed import (
    FRAME_BYTES,
    FRAME_PLAIN,
    ObjectRefused,
    Opener,
    digest_of,
    frame_count,
    new_key,
    open_object,
    seal_object,
    seal_part,
    sealed_parts,
    sealed_size,
)

REFERENCE = "org/exec_relay/session/item/1/file"


@pytest.mark.parametrize(
    "size", [0, 1, FRAME_PLAIN - 1, FRAME_PLAIN, FRAME_PLAIN + 1, 8 * FRAME_PLAIN, 21 * MIB + 3]
)
def test_the_parts_of_a_sealed_object_hold_whole_frames_and_seal_alone(size: int) -> None:
    data = os.urandom(size)
    key = new_key()
    parts = sealed_parts(size)
    assert tuple(part.size_bytes for part in parts) == part_sizes(sealed_size(size))
    assert sum(part.plain_size for part in parts) == size
    assert sum(part.frames for part in parts) == frame_count(size)
    for part in parts[:-1]:
        assert part.size_bytes % FRAME_BYTES == 0, "every part but the last is whole frames"
    whole = b"".join(seal_part(key, REFERENCE, data, part) for part in parts)
    assert len(whole) == sealed_size(size)
    assert open_object(key, REFERENCE, size, digest_of(data), whole) == data
    # Sealed again on a resume, a part stands beside the ones the store kept.
    again = seal_part(key, REFERENCE, data, parts[0])
    resumed = again + whole[parts[0].size_bytes :]
    assert open_object(key, REFERENCE, size, digest_of(data), resumed) == data


def test_an_object_opens_as_its_bytes_arrive_in_any_chunks() -> None:
    data = os.urandom(3 * FRAME_PLAIN + 17)
    key = new_key()
    sealed = seal_object(key, REFERENCE, data)
    opener = Opener(key, REFERENCE, len(data))
    opened = b"".join(
        b"".join(opener.feed(sealed[start : start + 70_001]))
        for start in range(0, len(sealed), 70_001)
    )
    opener.close()
    assert opened == data


def test_an_object_that_is_not_what_it_was_declared_is_refused() -> None:
    data = os.urandom(2 * FRAME_PLAIN + 5)
    key = new_key()
    sealed = seal_object(key, REFERENCE, data)
    digest = digest_of(data)
    flipped = bytearray(sealed)
    flipped[FRAME_BYTES + 40] ^= 1
    swapped = (
        sealed[FRAME_BYTES : 2 * FRAME_BYTES] + sealed[:FRAME_BYTES] + sealed[2 * FRAME_BYTES :]
    )
    cases = {
        "a byte changed": (key, REFERENCE, len(data), digest, bytes(flipped)),
        "frames swapped": (key, REFERENCE, len(data), digest, swapped),
        "its last frame dropped": (key, REFERENCE, len(data), digest, sealed[: 2 * FRAME_BYTES]),
        "bytes past its end": (key, REFERENCE, len(data), digest, sealed + b"x"),
        "another key": (new_key(), REFERENCE, len(data), digest, sealed),
        "another object's place": (key, REFERENCE + "-2", len(data), digest, sealed),
        "a size it was not": (key, REFERENCE, len(data) - 1, digest, sealed),
        "a digest it was not": (key, REFERENCE, len(data), digest_of(b"other"), sealed),
    }
    for case, (opened_with, reference, size, declared, held) in cases.items():
        with pytest.raises(ObjectRefused):
            open_object(opened_with, reference, size, declared, held)
            pytest.fail(case)
