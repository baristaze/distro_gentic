"""Pure rules of the watch: the live-read handle, signed and verified.
Values in, values out; no storage, no clock.

A handle is the grant it names, signed with the platform's key, the way a
presigned URL is: whoever holds it reads one session's open streams, or one
item's streams of one kind, until it expires, and a reader that changes a
byte of it reads nothing. The signature is checked before anything of the
grant is read, and each grant is signed for its own purpose, so a session's
handle never reads an item's streams, nor an item's a session's."""

import base64
import hashlib
import hmac

from pydantic import BaseModel

from acme.om.watch.types.live import Grant, ItemGrant

MIN_KEY = 32
"""The fewest bytes a signing key holds."""

MAX_HANDLE = 1024
"""The longest text read as a handle: anything longer is none."""

PURPOSE = b"live-read:"
"""What the signature covers besides a session's grant, so a signature made
for anything else with the same key never verifies as one."""

ITEM_PURPOSE = b"item-read:"
"""What the signature covers besides an item's grant."""


def _encoded(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decoded(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(key: bytes, purpose: bytes, body: str) -> bytes:
    return hmac.new(key, purpose + body.encode(), hashlib.sha256).digest()


def _purpose(grant: Grant | ItemGrant) -> bytes:
    return ITEM_PURPOSE if isinstance(grant, ItemGrant) else PURPOSE


def signed(key: bytes, grant: Grant | ItemGrant) -> str:
    """The handle of a grant: the grant, then its signature for the grant's
    own purpose."""
    if len(key) < MIN_KEY:
        raise ValueError(f"a signing key holds at least {MIN_KEY} bytes")
    body = _encoded(grant.model_dump_json().encode())
    return f"{body}.{_encoded(_mac(key, _purpose(grant), body))}"


def verified(key: bytes, handle: str) -> Grant | None:
    """The session's grant a handle carries, or None for text that is no
    handle or whose signature does not verify as a session's. Whether it
    expired is the caller's to read, against its clock."""
    return _verified(key, handle, PURPOSE, Grant)


def verified_item(key: bytes, handle: str) -> ItemGrant | None:
    """The item's grant a handle carries, or None, as `verified` reads a
    session's."""
    return _verified(key, handle, ITEM_PURPOSE, ItemGrant)


def _verified[G: BaseModel](key: bytes, handle: str, purpose: bytes, model: type[G]) -> G | None:
    if len(handle) > MAX_HANDLE or not handle.isascii():
        return None
    body, dot, mac = handle.partition(".")
    if not dot or not body or not mac:
        return None
    try:
        given = _decoded(mac)
    except ValueError:
        return None
    if not hmac.compare_digest(_mac(key, purpose, body), given):
        return None
    try:
        return model.model_validate_json(_decoded(body))
    except ValueError:
        return None
