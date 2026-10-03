"""Slack's side of the chat: the check of a delivery's signature, and the
reading of a delivery into the platform's terms. Slack's own event names
stay here.

Slack signs a delivery with HMAC-SHA256 of `v0:<timestamp>:<body>` under
the app's signing secret, sent as `v0=<hex>` in `X-Slack-Signature`, the
timestamp in `X-Slack-Request-Timestamp`, and checked inside a five-minute
window. A delivery's id is the event's id, in the signed body, so Slack's
retry of it is the same key. The installation is the workspace, by its
team id.

A message names its account by its user id. The platform's own account is
the app's bot user, which the client is given. A message the platform
posted is named `<channel>:<ts>`, and a reply names the message it
follows the same way among its refs, so a reply in a thread the platform
started follows from the platform's act. The platform's mark rides in the
message's metadata and is read back only from a message the platform's
account wrote.

What is read: a message, which addresses the agent when it is direct or
mentions the platform's account, and is a chat message otherwise. Slack's
check of the address it delivers to (`url_verification`) is acknowledged
with its challenge. Any other delivery, an edit or a deletion among them,
is refused, and nothing is queued for it."""

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from acme.integrations.events import Acknowledged, ProvidedEvent, delivery_key
from acme.integrations.exceptions import DeliveryRefused

SIGNATURE_HEADER = "x-slack-signature"
TIMESTAMP_HEADER = "x-slack-request-timestamp"
TOLERANCE = timedelta(minutes=5)
CHAT = "chat"
MARK_EVENT = "platform_act"
"""The metadata's event type on a message the platform posts."""
READ_SUBTYPES = frozenset({None, "bot_message", "thread_broadcast", "file_share"})
"""A message's subtypes that are a message someone wrote."""


def sign(payload: bytes, secret: str, at: datetime) -> dict[str, str]:
    """The headers Slack sends with `payload` at `at`."""
    stamp = str(int(at.timestamp()))
    digest = hmac.new(secret.encode(), f"v0:{stamp}:".encode() + payload, hashlib.sha256)
    return {SIGNATURE_HEADER: f"v0={digest.hexdigest()}", TIMESTAMP_HEADER: stamp}


def message_id(channel: str, ts: str) -> str:
    """A message's name: its channel and its timestamp, which only together
    name one message."""
    return f"{channel}:{ts}"


def verified(payload: bytes, headers: Mapping[str, str], secret: str, now: datetime) -> Any:
    """The delivery's body, once its signature checks out at `now`;
    `DeliveryRefused` otherwise, naming what failed and never the secret."""
    signature, stamp = headers.get(SIGNATURE_HEADER), headers.get(TIMESTAMP_HEADER)
    if not signature or not stamp:
        raise DeliveryRefused("no signature")
    if not stamp.isdigit() or not signature.startswith("v0="):
        raise DeliveryRefused("the signature is not v0=... with a timestamp")
    if abs(int(now.timestamp()) - int(stamp)) > TOLERANCE.total_seconds():
        raise DeliveryRefused("the signature's timestamp is outside the window")
    expected = hmac.new(secret.encode(), f"v0:{stamp}:".encode() + payload, hashlib.sha256)
    given = signature.removeprefix("v0=")
    if not given.isascii() or not hmac.compare_digest(given, expected.hexdigest()):
        raise DeliveryRefused("the signature did not check out")
    try:
        return json.loads(payload)
    except json.JSONDecodeError, UnicodeDecodeError:
        raise DeliveryRefused("the body is not JSON") from None


def read_delivery(
    payload: bytes, headers: Mapping[str, str], secret: str, account: str, now: datetime
) -> ProvidedEvent | Acknowledged:
    """A delivery Slack sent, checked and read. `account` is the user id of
    the platform's own bot."""
    body = verified(payload, headers, secret, now)
    if not isinstance(body, dict):
        raise DeliveryRefused("the body is not a delivery")
    if body.get("type") == "url_verification":
        challenge = body.get("challenge")
        if not isinstance(challenge, str) or not challenge:
            raise DeliveryRefused("the address check carries no challenge")
        return Acknowledged(challenge=challenge)
    if body.get("type") != "event_callback":
        raise DeliveryRefused(f"the chat takes no {body.get('type') or 'untyped'} delivery")
    event = body.get("event")
    if not isinstance(event, dict) or event.get("type") != "message":
        kind = event.get("type") if isinstance(event, dict) else None
        raise DeliveryRefused(f"the chat takes no {kind or 'untyped'} event")
    if event.get("subtype") not in READ_SUBTYPES:
        raise DeliveryRefused(f"the chat takes no message {event.get('subtype')}")
    try:
        fields = _message(event, account)
        delivery_id, installation = str(body["event_id"]), str(body["team_id"])
    except KeyError, TypeError, ValueError, AttributeError:
        raise DeliveryRefused("the body is not an event") from None
    try:
        return ProvidedEvent.model_validate(
            {
                "key": delivery_key(CHAT, delivery_id),
                "delivery_id": delivery_id,
                "installation": installation,
                **fields,
            }
        )
    except ValidationError:
        raise DeliveryRefused("the body is not an event") from None


def _message(event: Mapping[str, Any], account: str) -> dict[str, Any]:
    channel, ts = str(event["channel"]), str(event["ts"])
    text = str(event.get("text") or "")
    user = event.get("user")
    if user == account:
        kind, author_id, name = "platform", account, account
    elif event.get("bot_id") or event.get("subtype") == "bot_message":
        kind = "bot"
        author_id = str(event.get("bot_id") or user)
        name = str(event.get("username") or author_id)
    else:
        kind, author_id = "person", str(event["user"])
        profile = event.get("user_profile")
        profile = profile if isinstance(profile, dict) else {}
        name = str(profile.get("display_name") or profile.get("real_name") or author_id)
    refs = [message_id(channel, ts)]
    thread = event.get("thread_ts")
    if thread and str(thread) != ts:
        refs.append(message_id(channel, str(thread)))
    if kind == "platform":
        metadata = event.get("metadata")
        if isinstance(metadata, dict) and metadata.get("event_type") == MARK_EVENT:
            mark = (metadata.get("event_payload") or {}).get("mark")
            if isinstance(mark, str) and mark:
                refs.append(mark)
    addressed = event.get("channel_type") == "im" or f"<@{account}>" in text
    return {
        "arrival": "message" if addressed else "chat",
        "author_kind": kind,
        "author_id": author_id,
        "author_name": name,
        "refs": tuple(refs),
        "text": text,
        "occurred_at": datetime.fromtimestamp(float(ts), UTC),
    }
