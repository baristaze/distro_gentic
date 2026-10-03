"""The chat as a Slack app, over Slack's recorded deliveries and answers and
a transport that reaches no network: a delivery checks out only under the
app's signing secret, inside its window, and reads into the platform's
terms; Slack's check of the address is answered with its challenge; a grant
names its workspace only once Slack confirms the code; and a post carries
the platform's mark."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from acme.integrations.events import Acknowledged, ProvidedEvent, delivery_key
from acme.integrations.events.slack import SlackImpl
from acme.integrations.events.slack_wire import SIGNATURE_HEADER, sign
from acme.integrations.exceptions import DeliveryRefused, ProviderRefused, ProviderUnavailable

FIXTURES = Path(__file__).parent / "fixtures" / "slack"
SECRET = "the-apps-signing-secret"
BOT_TOKEN = "the-apps-bot-token"
ACCOUNT = "U0PLATFRM"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
MARK = "0b0e9a52-6a7e-4f43-9d1c-3c2b8c1f7e11"

Handler = Callable[[httpx.Request], httpx.Response]


def recorded(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def chat(handler: Handler) -> SlackImpl:
    return SlackImpl(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        bot_token=SecretStr(BOT_TOKEN),
        signing_secret=SecretStr(SECRET),
        client_id="1111.2222",
        client_secret=SecretStr("the-oauth-client-secret"),
        account=ACCOUNT,
    )


def unreachable(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no call was expected: {request.method} {request.url}")


def delivery(name: str, secret: str = SECRET, at: datetime = NOW) -> tuple[bytes, dict[str, str]]:
    payload = recorded(name)
    return payload, sign(payload, secret, at)


READ = [
    (
        "message_mention",
        {
            "arrival": "message",
            "author_kind": "person",
            "author_id": "U0PERSON1",
            "author_name": "ann",
            "refs": ("C0CHAN001:1790000000.000100",),
        },
    ),
    (
        "message_thread_reply",
        {
            "arrival": "chat",
            "author_kind": "person",
            "author_id": "U0PERSON2",
            "refs": ("C0CHAN001:1790000100.000200", "C0CHAN001:1790000050.000150"),
            "text": "same here, it broke after the last release",
        },
    ),
    (
        "message_by_the_platform",
        {
            "arrival": "message",
            "author_kind": "platform",
            "refs": ("D0DIRECT01:1790000050.000150", MARK),
        },
    ),
]


@pytest.mark.parametrize(("name", "expected"), READ, ids=[r[0] for r in READ])
def test_a_recorded_delivery_reads_into_its_event(name: str, expected: dict[str, Any]) -> None:
    payload, headers = delivery(name)
    read = chat(unreachable).verify_delivery(payload, headers, NOW)
    assert isinstance(read, ProvidedEvent)
    assert read.installation == "T0TEAM001"
    assert {field: getattr(read, field) for field in expected} == expected
    # Slack's retry carries the same event id, so it is the same key.
    assert read.key == delivery_key("chat", json.loads(payload)["event_id"])


def test_the_address_check_is_answered_with_its_challenge() -> None:
    read = chat(unreachable).verify_delivery(*delivery("url_verification"), NOW)
    assert read == Acknowledged(challenge=json.loads(recorded("url_verification"))["challenge"])


def test_an_edit_is_refused() -> None:
    with pytest.raises(DeliveryRefused, match="message_changed"):
        chat(unreachable).verify_delivery(*delivery("message_changed"), NOW)


@pytest.mark.parametrize("tamper", ["body", "secret", "missing", "stale", "challenge"])
def test_a_delivery_that_does_not_check_out_is_refused(tamper: str) -> None:
    name = "url_verification" if tamper == "challenge" else "message_mention"
    payload, headers = delivery(name)
    if tamper == "body":
        payload = payload.replace(b"take a look", b"merge it now")
    elif tamper in ("secret", "challenge"):
        payload, headers = delivery(name, secret="a-forged-secret")
    elif tamper == "missing":
        del headers[SIGNATURE_HEADER]
    else:
        payload, headers = delivery(name, at=NOW - timedelta(minutes=6))
    with pytest.raises(DeliveryRefused) as refused:
        chat(unreachable).verify_delivery(payload, headers, NOW)
    assert SECRET not in str(refused.value)


def oauth(ok: bool = True) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/oauth.v2.access"
        if not ok:
            return httpx.Response(200, json={"ok": False, "error": "invalid_code"})
        return httpx.Response(200, content=recorded("oauth_access"))

    return handle


async def test_a_grant_names_its_workspace_once_slack_confirms_the_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = chat(oauth())
    assert await client.verify_installation("a-code", NOW) == "T0TEAM001"
    # The workspace's token the trade answers is kept nowhere and shown nowhere.
    kept = json.loads(recorded("oauth_access"))["access_token"]
    assert kept not in repr(vars(client)) and kept not in caplog.text


@pytest.mark.parametrize("grant", ["a-code", ""])
async def test_a_grant_slack_does_not_confirm_is_refused(grant: str) -> None:
    with pytest.raises(DeliveryRefused):
        await chat(oauth(ok=False)).verify_installation(grant, NOW)


async def test_a_post_carries_its_mark_and_answers_as_real() -> None:
    sent: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=recorded("post_message"))

    posted = await chat(handle).post("U0PERSON1", "A call waits on your approval.", MARK)
    assert (posted.id, posted.provenance, posted.mark) == (
        "D0DIRECT01:1790000300.000400",
        "real",
        MARK,
    )
    (request,) = sent
    assert request.headers["authorization"] == f"Bearer {BOT_TOKEN}"
    assert json.loads(request.content)["metadata"]["event_payload"] == {"mark": MARK}


@pytest.mark.parametrize(
    ("error", "raised"),
    [("invalid_auth", ProviderUnavailable), ("channel_not_found", ProviderRefused)],
)
async def test_a_refused_key_is_unavailable_and_a_refused_post_is_refused(
    error: str, raised: type[Exception]
) -> None:
    client = chat(lambda request: httpx.Response(200, json={"ok": False, "error": error}))
    with pytest.raises(raised) as failed:
        await client.post("U0PERSON1", "text")
    assert BOT_TOKEN not in str(failed.value)


async def test_the_chat_holds_no_repository() -> None:
    with pytest.raises(ProviderRefused):
        await chat(unreachable).push(
            "https://github.com/o/r.git", "refs/heads/x", "abc", b"", installation="1"
        )
