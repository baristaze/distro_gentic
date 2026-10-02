"""What crosses a customer's wall, and the check every crossing passes.

Enrollment, claims, stream parts, artifacts, and results cross between the
platform's cloud and a host inside a customer's wall. Each is opened from
inside the wall, and each arrives with the hash its sender declared. The
receiver verifies the bytes against that hash before it reads them, so a
payload changed on the way, or swapped for another, is refused and never
read as anything."""

import hashlib
import hmac
from enum import StrEnum

from pydantic import Field

from acme.om.base import Platform
from acme.om.exceptions import ValidationFailed

SHA256 = r"^[0-9a-f]{64}$"


class CrossingKind(StrEnum):
    ENROLLMENT = "enrollment"
    CLAIM = "claim"
    STREAM_PART = "stream_part"
    ARTIFACT = "artifact"
    RESULT = "result"


class CrossingRefused(ValidationFailed):
    """A crossing whose bytes are not the ones its sender declared."""

    code = "crossing_refused"


class Crossing(Platform):
    """What a sender declares of a payload it sends across the wall: what it
    is, its SHA-256 in hex, and its size in bytes."""

    kind: CrossingKind
    sha256: str = Field(pattern=SHA256)
    size: int = Field(ge=0)


def declared(kind: CrossingKind, payload: bytes) -> Crossing:
    """The declaration a sender makes of `payload`."""
    return Crossing(kind=kind, sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))


def verified(crossing: Crossing, payload: bytes) -> bytes:
    """`payload`, once it is the one `crossing` declares: its size and its
    hash both match, the hash compared in constant time. `CrossingRefused`
    otherwise, naming what crossed and never what it holds."""
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != crossing.size or not hmac.compare_digest(digest, crossing.sha256):
        raise CrossingRefused(f"a {crossing.kind.value} does not match the hash it crossed with")
    return payload
