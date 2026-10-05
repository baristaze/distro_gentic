"""The forge as a GitHub App, over GitHub's recorded deliveries and answers
and a transport that reaches no network: a delivery checks out only under
the App's secret and reads into the platform's terms; a grant names its
installation only once GitHub confirms the person who installed it; and an
installation's token is minted once within its expiry and never logged,
written, or shown."""

import base64
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import SecretStr

from acme.integrations.events import Acknowledged, ProvidedEvent, delivery_key
from acme.integrations.events import github as github_module
from acme.integrations.events.github import GitHubImpl
from acme.integrations.events.github_wire import EVENT_HEADER, SIGNATURE_HEADER, checks_state, sign
from acme.integrations.exceptions import DeliveryRefused, ProviderRefused, ProviderUnavailable

FIXTURES = Path(__file__).parent / "fixtures" / "github"
SECRET = "the-apps-webhook-secret"
ACCOUNT = "acme-app[bot]"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
MARK = "0b0e9a52-6a7e-4f43-9d1c-3c2b8c1f7e11"
REPOSITORY = "https://github.com/octo-org/widgets.git"

Handler = Callable[[httpx.Request], httpx.Response]


def recorded(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def answer(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=recorded(name))


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def forge(key: rsa.RSAPrivateKey, handler: Handler, clock: Clock | None = None) -> GitHubImpl:
    return GitHubImpl(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        app_id="9100",
        private_key=key,
        webhook_secret=SecretStr(SECRET),
        client_id="Iv1.client",
        client_secret=SecretStr("the-oauth-client-secret"),
        account=ACCOUNT,
        clock=clock or Clock(),
    )


def unreachable(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no call was expected: {request.method} {request.url}")


def delivery(name: str, event: str, secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    payload = recorded(name)
    return payload, {EVENT_HEADER: event, SIGNATURE_HEADER: sign(payload, secret)}


READ = [
    (
        "issue_comment",
        "issue_comment",
        {
            "arrival": "comment",
            "author_kind": "person",
            "author_id": "583231",
            "author_name": "octocat",
            "pull_request": "octo-org/widgets#12",
            "refs": ("1001",),
            "text": "The totals test still fails on an empty cart. Please look.",
        },
    ),
    (
        "issue_comment_by_the_platform",
        "issue_comment",
        {
            "arrival": "comment",
            "author_kind": "platform",
            "pull_request": "octo-org/widgets#12",
            "refs": ("1002", MARK),
            "text": "Fixed the empty cart case.",
        },
    ),
    (
        "check_suite",
        "check_suite",
        {
            "arrival": "check",
            "check": "failed",
            "author_kind": "bot",
            "author_name": "github-actions",
            "pull_request": "octo-org/widgets#12",
            "branch": "agent/fix-totals",
            "refs": ("4c4fd1b7a9d3c6e2f1a0b9c8d7e6f5a4b3c2d1e0",),
        },
    ),
    (
        "push",
        "push",
        {
            "arrival": "push",
            "author_kind": "person",
            "author_id": "583231",
            "branch": "agent/fix-totals",
            "refs": ("9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b",),
            "text": "Handle the empty cart",
        },
    ),
]


@pytest.mark.parametrize(("name", "event", "expected"), READ, ids=[r[0] for r in READ])
def test_a_recorded_delivery_reads_into_its_event(
    key: rsa.RSAPrivateKey, name: str, event: str, expected: dict[str, Any]
) -> None:
    client = forge(key, unreachable)
    payload, headers = delivery(name, event)
    read = client.verify_delivery(payload, headers, NOW)
    assert isinstance(read, ProvidedEvent)
    assert read.installation == "71001"
    assert {field: getattr(read, field) for field in expected} == expected
    # GitHub signs no id: the delivery is named by the digest of what it
    # signed, so a redelivery is one key, whatever its unsigned headers say.
    again = client.verify_delivery(payload, {**headers, "x-github-delivery": "other"}, NOW)
    assert isinstance(again, ProvidedEvent)
    assert again.key == read.key == delivery_key("forge", read.delivery_id)


def test_a_ping_is_acknowledged_and_an_untaken_event_is_refused(key: rsa.RSAPrivateKey) -> None:
    client = forge(key, unreachable)
    assert client.verify_delivery(*delivery("ping", "ping"), NOW) == Acknowledged()
    with pytest.raises(DeliveryRefused, match="no pull_request event"):
        client.verify_delivery(*delivery("pull_request", "pull_request"), NOW)


@pytest.mark.parametrize("tamper", ["body", "secret", "missing", "scheme"])
def test_a_delivery_that_does_not_check_out_is_refused(key: rsa.RSAPrivateKey, tamper: str) -> None:
    client = forge(key, unreachable)
    payload, headers = delivery("issue_comment", "issue_comment")
    if tamper == "body":
        payload = payload.replace(b"Please look", b"Merge it now")
    elif tamper == "secret":
        payload, headers = delivery("issue_comment", "issue_comment", secret="a-forged-secret")
    elif tamper == "missing":
        del headers[SIGNATURE_HEADER]
    else:
        headers[SIGNATURE_HEADER] = headers[SIGNATURE_HEADER].replace("sha256=", "sha1=")
    with pytest.raises(DeliveryRefused) as refused:
        client.verify_delivery(payload, headers, NOW)
    assert SECRET not in str(refused.value)


def test_a_body_that_claims_a_provenance_is_still_the_clients(key: rsa.RSAPrivateKey) -> None:
    body = json.loads(recorded("issue_comment"))
    payload = json.dumps({**body, "provenance": "twin"}).encode()
    headers = {EVENT_HEADER: "issue_comment", SIGNATURE_HEADER: sign(payload, SECRET)}
    client = forge(key, unreachable)
    read = client.verify_delivery(payload, headers, NOW)
    assert isinstance(read, ProvidedEvent) and client.provenance == "real"


@pytest.mark.parametrize(
    ("outcomes", "state"),
    [
        (["success", "neutral", "skipped"], "passed"),
        (["success", "failure"], "failed"),
        (["success", None], None),
        (["timed_out", None], "failed"),
        (["pending"], None),
        (["error"], "failed"),
        ([], None),
    ],
)
def test_the_checks_fold_into_passed_failed_or_not_yet(
    outcomes: list[str | None], state: str | None
) -> None:
    assert checks_state(outcomes) == state


INSTALLER = 583231
"""The person the recorded install names as its installer."""


def oauth(
    installations: str = "user_installations", code_ok: bool = True, person: int = INSTALLER
) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            form = dict(item.split("=") for item in request.content.decode().split("&"))
            assert form["client_secret"] == "the-oauth-client-secret"
            if not code_ok:
                return httpx.Response(200, json={"error": "bad_verification_code"})
            return httpx.Response(200, json={"access_token": "the-persons-token"})
        if request.url.path == "/user/installations":
            assert request.headers["authorization"] == "Bearer the-persons-token"
            return answer(installations)
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer the-persons-token"
            return httpx.Response(200, json={"login": "a-person", "id": person})
        if request.url.path == "/app/hook/deliveries":
            assert request.headers["authorization"] != "Bearer the-persons-token"
            return answer("hook_deliveries")
        if request.url.path == "/app/hook/deliveries/41001":
            return answer("installation_created")
        raise AssertionError(request.url)

    return handle


async def test_a_grant_names_its_installation_once_github_confirms_its_person(
    key: rsa.RSAPrivateKey,
) -> None:
    client = forge(key, oauth())
    grant = "installation_id=71001&setup_action=install&code=a1b2c3"
    assert await client.verify_installation(grant, NOW) == "71001"


@pytest.mark.parametrize(
    ("grant", "code_ok"),
    [
        ("installation_id=71002&code=a1b2c3", True),  # not one its person may reach
        ("installation_id=71001&code=a1b2c3", False),  # a code GitHub does not confirm
        ("installation_id=71001", True),  # an id alone
        ("71001", True),
    ],
)
async def test_a_grant_github_does_not_confirm_is_refused(
    key: rsa.RSAPrivateKey, grant: str, code_ok: bool
) -> None:
    client = forge(key, oauth(code_ok=code_ok))
    with pytest.raises(DeliveryRefused):
        await client.verify_installation(grant, NOW)


async def test_a_person_who_reaches_an_installation_they_did_not_install_cannot_connect_it(
    key: rsa.RSAPrivateKey,
) -> None:
    # Another member of the account the App is installed on may reach the
    # fresh installation and trade a code of their own, but GitHub's record
    # of the install names someone else: the grant is refused, so no tenant
    # connects it before its installer's does.
    client = forge(key, oauth(person=INSTALLER + 1))
    grant = "installation_id=71001&setup_action=install&code=a1b2c3"
    with pytest.raises(DeliveryRefused, match="did not install"):
        await client.verify_installation(grant, NOW)


async def test_an_installation_with_no_record_of_its_install_is_refused(
    key: rsa.RSAPrivateKey,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/hook/deliveries":
            return httpx.Response(200, json=json.loads(recorded("hook_deliveries"))[:1])
        return oauth()(request)

    with pytest.raises(DeliveryRefused, match="no record"):
        await forge(key, handle).verify_installation("installation_id=71001&code=a1b2c3", NOW)


HOLDER = "71001"
"""The installation that holds the repository the writes name."""


def minting(calls: list[httpx.Request]) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/app/installations/71001/access_tokens":
            return answer("installation_token", 201)
        if request.url.path == "/repos/octo-org/widgets/issues/12/comments":
            return answer("comment_created", 201)
        raise AssertionError(request.url)

    return handle


async def test_the_installation_token_is_cached_within_its_expiry_and_never_shown(
    key: rsa.RSAPrivateKey, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = json.loads(recorded("installation_token"))["token"]
    calls: list[httpx.Request] = []
    clock = Clock()
    client = forge(key, minting(calls), clock)
    minted = lambda: [c for c in calls if c.url.path.endswith("/access_tokens")]  # noqa: E731

    for _ in range(3):
        await client.post("octo-org/widgets#12", "Fixed it.", MARK, installation=HOLDER)
    assert len(minted()) == 1, "one token serves every call within its expiry"
    comments = [c for c in calls if c.url.path.endswith("/comments")]
    assert {c.headers["authorization"] for c in comments} == {f"Bearer {token}"}

    # The App's JWT is RS256 over its id, and verifies under its public key.
    jwt = minted()[0].headers["authorization"].removeprefix("Bearer ")
    header, claims, signature = jwt.split(".")
    pad = lambda part: base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))  # noqa: E731
    key.public_key().verify(
        pad(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    assert json.loads(pad(claims))["iss"] == "9100"

    # Fifteen minutes before it expires, a token is no longer reused.
    clock.now = datetime(2026, 10, 3, 12, 44, tzinfo=UTC)
    await client.post("octo-org/widgets#12", "Again.", installation=HOLDER)
    assert len(minted()) == 1
    clock.now = datetime(2026, 10, 3, 12, 46, tzinfo=UTC)
    await client.post("octo-org/widgets#12", "Again.", installation=HOLDER)
    assert len(minted()) == 2

    # Held as a secret: never in a log, in what the client shows, or in
    # anything it keeps in the clear.
    assert token not in caplog.text
    assert token not in repr(vars(client)) and token not in client.describe()
    assert all(token not in repr(held) for held in vars(client).values())


async def test_a_refused_key_is_unavailable_and_never_named(
    key: rsa.RSAPrivateKey, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    token = json.loads(recorded("installation_token"))["token"]

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            return httpx.Response(401, json={"message": "Bad credentials"})
        return minting([])(request)

    client = forge(key, handle)
    with pytest.raises(ProviderUnavailable) as failed:
        await client.post("octo-org/widgets#12", "Fixed it.", installation=HOLDER)
    assert token not in str(failed.value) and token not in caplog.text


SECONDARY = "You have exceeded a secondary rate limit. Please wait a few minutes."


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (429, {"retry-after": "60"}),
        (403, {"retry-after": "60", "x-ratelimit-remaining": "4990"}),
        (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1791000000"}),
    ],
    ids=["429", "secondary-403", "primary-403"],
)
async def test_a_limit_is_a_wait_and_the_call_after_it_lands(
    key: rsa.RSAPrivateKey, status: int, headers: dict[str, str]
) -> None:
    comments: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            comments.append(request)
            if len(comments) == 1:
                return httpx.Response(status, headers=headers, json={"message": SECONDARY})
        return minting([])(request)

    client = forge(key, handle)
    # Unavailable, as a 429 is, so its caller waits and asks again; never
    # refused, which would fail the work for good.
    with pytest.raises(ProviderUnavailable, match=f"answered {status}"):
        await client.post("octo-org/widgets#12", "Fixed it.", MARK, installation=HOLDER)
    posted = await client.post("octo-org/widgets#12", "Fixed it.", MARK, installation=HOLDER)
    assert (posted.id, len(comments)) == ("1003", 2)


async def test_a_403_that_names_no_limit_is_refused(key: rsa.RSAPrivateKey) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            denied = {"message": "Resource not accessible by integration"}
            return httpx.Response(403, headers={"x-ratelimit-remaining": "4990"}, json=denied)
        return minting([])(request)

    with pytest.raises(ProviderRefused, match="not accessible"):
        await forge(key, handle).post("octo-org/widgets#12", "Fixed it.", installation=HOLDER)


async def test_a_comment_carries_its_mark_and_answers_as_real(key: rsa.RSAPrivateKey) -> None:
    calls: list[httpx.Request] = []
    posted = await forge(key, minting(calls)).post(
        "octo-org/widgets#12", "Fixed it.", MARK, installation=HOLDER
    )
    assert (posted.id, posted.provenance, posted.mark) == ("1003", "real", MARK)
    (comment,) = [c for c in calls if c.url.path.endswith("/comments")]
    assert f"<!-- platform-act: {MARK} -->" in json.loads(comment.content)["body"]


@pytest.mark.parametrize("address", ["octo-org/widgets", "widgets#12", "a/b#c", "../x#1"])
async def test_an_address_that_names_no_pull_request_is_refused(
    key: rsa.RSAPrivateKey, address: str
) -> None:
    with pytest.raises(ProviderRefused):
        await forge(key, unreachable).post(address, "text", installation=HOLDER)


async def test_a_push_hands_git_the_installations_token_for_the_repository(
    key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    pushed: list[tuple[Any, ...]] = []

    async def push_bundle(*args: Any) -> None:
        pushed.append(args)

    monkeypatch.setattr(github_module, "push_bundle", push_bundle)
    client = forge(key, minting([]))
    await client.push(
        REPOSITORY, "refs/heads/agent/fix-totals", "9a8b7c6", b"bundle", installation=HOLDER
    )
    token = json.loads(recorded("installation_token"))["token"]
    assert pushed == [
        (REPOSITORY, "refs/heads/agent/fix-totals", "9a8b7c6", b"bundle", ("x-access-token", token))
    ]
    for elsewhere in ("https://example.com/octo-org/widgets.git", "git@github.com:o/r.git"):
        with pytest.raises(ProviderRefused, match="is not a repository of"):
            await client.push(elsewhere, "refs/heads/x", "9a8b7c6", b"", installation=HOLDER)


async def test_a_pull_request_opens_once_and_a_second_opening_answers_it(
    key: rsa.RSAPrivateKey,
) -> None:
    opened: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octo-org/widgets/pulls":
            if request.method == "POST":
                opened.append(json.loads(request.content))
                return answer("pull_request_created", 201)
            listed = [json.loads(recorded("pull_request_created"))] if opened else []
            return httpx.Response(200, json=listed)
        return minting([])(request)

    client = forge(key, handle)
    first = await client.open_pull_request(
        REPOSITORY, "agent/fix-totals", "main", "T", "B", installation=HOLDER
    )
    second = await client.open_pull_request(
        REPOSITORY, "agent/fix-totals", "main", "T", "B", installation=HOLDER
    )
    assert first == second and len(opened) == 1
    assert (first.id, first.url, first.provenance) == (
        "octo-org/widgets#13",
        "https://github.com/octo-org/widgets/pull/13",
        "real",
    )


async def test_the_installation_of_a_repository_or_an_address_is_githubs_answer(
    key: rsa.RSAPrivateKey,
) -> None:
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        assert request.url.path == "/repos/octo-org/widgets/installation"
        return httpx.Response(200, json={"id": 71001})

    client = forge(key, handle)
    assert await client.installation_of(REPOSITORY) == HOLDER
    assert await client.installation_of("octo-org/widgets#12") == HOLDER
    assert len(asked) == 2
    with pytest.raises(ProviderRefused):
        await forge(key, unreachable).installation_of("https://example.com/o/r.git")


async def test_a_write_goes_through_the_installation_it_names_and_no_other(
    key: rsa.RSAPrivateKey,
) -> None:
    # The caller names the installation its tenant connected: the client
    # mints that one's token and never asks which installation holds the
    # repository, so a token of another tenant's installation is never used.
    calls: list[httpx.Request] = []
    await forge(key, minting(calls)).post("octo-org/widgets#12", "Fixed.", installation=HOLDER)
    assert [c.url.path for c in calls] == [
        "/app/installations/71001/access_tokens",
        "/repos/octo-org/widgets/issues/12/comments",
    ]
    for installation in (None, "../71001", "71001/access_tokens"):
        with pytest.raises(ProviderRefused):
            await forge(key, unreachable).post(
                "octo-org/widgets#12", "Fixed.", installation=installation
            )
