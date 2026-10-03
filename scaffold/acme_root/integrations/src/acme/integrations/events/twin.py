"""An integration's twin: deterministic, in-process, and for a local
environment only (the configured root refuses it anywhere else). It
speaks the delivery shape the ingress reads, signs its own deliveries, and
records every message the platform posts through it.

It names its provenance on every record it writes: each delivery it signs
says `twin`, as does each message it records, and every id it mints
starts with `twin_`. And what it verifies is a twin's event whatever the
body claims, since the integration says what served it, never the
delivery.

The signature is HMAC-SHA256 over `<timestamp>.<body>` under the twin's
secret, the timestamp in whole seconds, sent as `t=<timestamp>,
v1=<signature>` in `Twin-Signature`, and checked inside a five-minute
window in constant time. An installation's grant is signed the same way
over `<timestamp>.installation:<installation>`, and carried as
`<installation>;t=<timestamp>, v1=<signature>`.

The forge's twin holds the refs the platform points and the pull requests
it opens, by name and head. Made with a repository's credential
(`writes_with`), it also pushes each ref's commits to the repository for
real, from the platform's bundle, as a forge does (`git.py`); made with
none, it holds names alone, with no commits behind them. Any other
integration's twin holds no repository."""

import hashlib
import hmac
import itertools
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from acme.integrations.events import (
    IntegrationInterface,
    OpenedPullRequest,
    PostedMessage,
    Provenance,
    ProvidedEvent,
    delivery_key,
)
from acme.integrations.events.git import push_bundle
from acme.integrations.exceptions import DeliveryRefused, ProviderRefused

SIGNATURE_HEADER = "twin-signature"
TOLERANCE = timedelta(minutes=5)
TWIN_SECRET = "twin-integration-secret"
"""The secret every twin signs with; never a real integration's."""

TWIN = "twin"
FORGE = "forge"


def sign(payload: bytes, secret: str, at: datetime) -> str:
    """The header a delivery of `payload` carries at `at`."""
    stamp = int(at.timestamp())
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={stamp}, v1={digest}"


def _granted(installation: str) -> bytes:
    """What an installation's grant signs: never a delivery's body, which is
    JSON."""
    return f"installation:{installation}".encode()


def verified(payload: bytes, signature: str | None, secret: str, now: datetime) -> dict[str, Any]:
    """The delivery's body, once its signature checks out at `now`;
    `DeliveryRefused` otherwise, naming what failed and never the secret."""
    verified_signature(payload, signature, secret, now)
    try:
        body = json.loads(payload)
    except json.JSONDecodeError, UnicodeDecodeError:
        raise DeliveryRefused("the body is not JSON") from None
    if not isinstance(body, dict):
        raise DeliveryRefused("the body is not a delivery")
    return body


def verified_signature(payload: bytes, signature: str | None, secret: str, now: datetime) -> None:
    """Nothing, once `signature` over `payload` checks out at `now`;
    `DeliveryRefused` otherwise, naming what failed and never the secret."""
    if not signature:
        raise DeliveryRefused("no signature")
    try:
        stamp, digest = (part.strip() for part in signature.split(","))
        if not stamp.startswith("t=") or not digest.startswith("v1="):
            raise ValueError
        at = int(stamp[2:])
    except ValueError:
        raise DeliveryRefused("the signature is not t=..., v1=...") from None
    if abs(int(now.timestamp()) - at) > TOLERANCE.total_seconds():
        raise DeliveryRefused("the signature's timestamp is outside the window")
    expected = hmac.new(secret.encode(), f"{at}.".encode() + payload, hashlib.sha256).hexdigest()
    given = digest[3:]
    if not given.isascii() or not hmac.compare_digest(given, expected):
        raise DeliveryRefused("the signature did not check out")


class IntegrationTwinImpl(IntegrationInterface):
    def __init__(
        self,
        name: str,
        secret: str = TWIN_SECRET,
        writes_with: tuple[str, str] | None = None,
    ) -> None:
        self._name = name
        self._secret = secret
        self._writes_with = writes_with
        self._counter = itertools.count(1)
        self.posted: list[PostedMessage] = []
        """Every message the platform posted through the twin, in order."""
        self.refs: dict[tuple[str, str], str] = {}
        """Each ref the platform pointed, by repository and full name: its
        head."""
        self.pull_requests: list[OpenedPullRequest] = []
        """Every pull request the platform opened through the twin, in order."""

    def _id(self, kind: str) -> str:
        return f"twin_{kind}_{next(self._counter):06d}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def provenance(self) -> Provenance:
        return TWIN

    def deliver(
        self, installation: str, at: datetime, **event: object
    ) -> tuple[bytes, dict[str, str]]:
        """A delivery the twin's system sends at `at`: its body and its
        headers. `event` holds the event's fields in the platform's terms
        (`ProvidedEvent`); the twin mints the delivery's id, and an author's
        when the event names none, and says it served the delivery."""
        body = {
            "delivery_id": self._id("delivery"),
            "installation": installation,
            "author_id": self._id("account"),
            "author_name": "twin",
            "occurred_at": at.isoformat(),
            **{key: value for key, value in event.items() if value is not None},
            "provenance": TWIN,
        }
        payload = json.dumps(body, default=str).encode()
        return payload, {SIGNATURE_HEADER: sign(payload, self._secret, at)}

    def grant(self, installation: str, at: datetime) -> str:
        """The grant the twin's system hands the person who installs the
        platform as `installation`, at `at`."""
        return f"{installation};{sign(_granted(installation), self._secret, at)}"

    async def verify_installation(self, grant: str, now: datetime) -> str:
        installation, _, signature = grant.rpartition(";")
        if not installation:
            raise DeliveryRefused("the grant names no installation")
        verified_signature(_granted(installation), signature, self._secret, now)
        return installation

    def verify_delivery(
        self, payload: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProvidedEvent:
        body = verified(payload, headers.get(SIGNATURE_HEADER), self._secret, now)
        # What served it is the twin's word: a provenance the body states is
        # read as nothing.
        body.pop("provenance", None)
        delivery_id = body.get("delivery_id")
        if not isinstance(delivery_id, str) or not delivery_id:
            raise DeliveryRefused("the body names no delivery")
        try:
            return ProvidedEvent.model_validate(
                {**body, "key": delivery_key(self._name, delivery_id)}
            )
        except ValidationError:
            raise DeliveryRefused("the body is not an event") from None

    async def post(self, address: str, text: str, mark: str | None = None) -> PostedMessage:
        message = PostedMessage(
            id=self._id("message"),
            address=address,
            text=text,
            provenance=TWIN,
            posted_at=datetime.now(UTC),
            mark=mark,
        )
        self.posted.append(message)
        return message

    async def push(self, repository: str, ref: str, head: str, bundle: bytes) -> None:
        self._holds_repositories()
        if self._writes_with is not None:
            await push_bundle(repository, ref, head, bundle, self._writes_with)
        self.refs[(repository, ref)] = head

    async def open_pull_request(
        self, repository: str, head: str, base: str | None, title: str, body: str
    ) -> OpenedPullRequest:
        self._holds_repositories()
        if (repository, f"refs/heads/{head}") not in self.refs:
            raise ProviderRefused(f"{repository} has no branch {head}")
        for opened in self.pull_requests:
            if (opened.repository, opened.head) == (repository, head):
                return opened
        number = len(self.pull_requests) + 1
        opened = OpenedPullRequest(
            id=self._id("pull_request"),
            url=f"twin://{repository}/pull/{number}",
            repository=repository,
            head=head,
            base=base,
            title=title,
            body=body,
            provenance=TWIN,
        )
        self.pull_requests.append(opened)
        return opened

    def _holds_repositories(self) -> None:
        if self._name != FORGE:
            raise ProviderRefused(f"the {self._name} twin holds no repository")

    def describe(self) -> str:
        return f"{self._name}=twin"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
