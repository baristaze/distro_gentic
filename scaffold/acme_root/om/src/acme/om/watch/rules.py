"""Pure rules of the watch: the live-read handle, signed and verified.
Values in, values out; no storage, no clock.

A handle is the grant it names, signed with the platform's key, the way a
presigned URL is: whoever holds it reads one session's open streams until
it expires, and a reader that changes a byte of it reads nothing. The
signature is checked before anything of the grant is read."""

import base64
import hashlib
import hmac

from acme.om.watch.types.live import Grant

MIN_KEY = 32
"""The fewest bytes a signing key holds."""

MAX_HANDLE = 1024
"""The longest text read as a handle: anything longer is none."""

PURPOSE = b"live-read:"
"""What the signature covers besides the grant, so a signature made for
anything else with the same key never verifies here."""


def _encoded(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decoded(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(key: bytes, body: str) -> bytes:
    return hmac.new(key, PURPOSE + body.encode(), hashlib.sha256).digest()


def signed(key: bytes, grant: Grant) -> str:
    """The handle of a grant: the grant, then its signature."""
    if len(key) < MIN_KEY:
        raise ValueError(f"a signing key holds at least {MIN_KEY} bytes")
    body = _encoded(grant.model_dump_json().encode())
    return f"{body}.{_encoded(_mac(key, body))}"


def verified(key: bytes, handle: str) -> Grant | None:
    """The grant a handle carries, or None for text that is no handle or
    whose signature does not verify. Whether it expired is the caller's to
    read, against its clock."""
    if len(handle) > MAX_HANDLE or not handle.isascii():
        return None
    body, dot, mac = handle.partition(".")
    if not dot or not body or not mac:
        return None
    try:
        given = _decoded(mac)
    except ValueError:
        return None
    if not hmac.compare_digest(_mac(key, body), given):
        return None
    try:
        return Grant.model_validate_json(_decoded(body))
    except ValueError:
        return None
