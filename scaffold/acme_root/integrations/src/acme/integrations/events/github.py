"""The forge as a GitHub App: GitHub's REST API over `httpx`, as the App's
installations reach it.

The App proves itself with a JWT it signs with its private key (RS256,
issued by the App's id, ten minutes long at most), and trades it for an
installation's token, which every call on that installation's
repositories carries. A token lasts an hour. The client keeps each
installation's in memory, as a secret, and reuses it until fifteen minutes
before it expires, longer than a push's git commands may take, so no call
starts on a token about to lapse. A token is never logged, never written,
and never in a message: a push hands it to git through the environment of
the commands that ask the repository (`git.py`).

A tenant connects an installation with the grant GitHub hands the person
who installed the App, the query of the setup redirect: the installation's
id and a code for that person. The code is traded for the person's token,
and the installation counts only when GitHub lists it among the ones that
person may reach. That token is used once and kept nowhere. The id alone
is never trusted (ADR 2020).

Deliveries are read in `github_wire.py`. The client's writes resolve the
installation of the repository they name, so one App serves every
installation of it."""

import asyncio
import base64
import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import SecretStr

from acme.infra.base import utcnow
from acme.integrations.events import (
    Acknowledged,
    IntegrationInterface,
    OpenedPullRequest,
    PostedMessage,
    Provenance,
    ProvidedEvent,
)
from acme.integrations.events.git import push_bundle
from acme.integrations.events.github_wire import FORGE, marked, read_delivery
from acme.integrations.exceptions import DeliveryRefused, ProviderRefused, ProviderUnavailable

log = logging.getLogger(__name__)

REAL: Provenance = "real"
API_VERSION = "2022-11-28"
JWT_LIFETIME = timedelta(minutes=9)
JWT_SKEW = timedelta(seconds=60)
"""A JWT is dated a minute back, so a clock behind GitHub's still passes."""
TOKEN_MARGIN = timedelta(minutes=15)
"""How long before its expiry a token stops being reused."""
MAX_INSTALLATION_PAGES = 10
"""The most pages of a person's installations read, a hundred to a page."""

ADDRESS = re.compile(r"^([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})#([0-9]{1,10})$")
"""A pull request or an issue: `<owner>/<repo>#<number>`."""
REPOSITORY = re.compile(r"^/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")


@dataclass(frozen=True)
class _Token:
    value: SecretStr
    expires_at: datetime


def load_private_key(pem: str) -> rsa.RSAPrivateKey:
    """The App's private key from its PEM, a line break written as `\\n`
    read as one; `ValueError` for anything but an RSA private key."""
    key = load_pem_private_key(pem.replace("\\n", "\n").encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("not an RSA private key")
    return key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class GitHubImpl(IntegrationInterface):
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        app_id: str,
        private_key: rsa.RSAPrivateKey,
        webhook_secret: SecretStr,
        client_id: str,
        client_secret: SecretStr,
        account: str,
        api_url: str = "https://api.github.com",
        web_url: str = "https://github.com",
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._http = http
        self._app_id = app_id
        self._private_key = private_key
        self._webhook_secret = webhook_secret
        self._client_id = client_id
        self._client_secret = client_secret
        self._account = account
        self._api = api_url.rstrip("/")
        self._web = web_url.rstrip("/")
        self._host = urlsplit(self._web).netloc
        self._clock = clock
        self._tokens: dict[str, _Token] = {}
        self._minting = asyncio.Lock()

    @property
    def name(self) -> str:
        return FORGE

    @property
    def provenance(self) -> Provenance:
        return REAL

    def describe(self) -> str:
        return f"{FORGE}=github app={self._app_id} account={self._account}"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        await self._http.aclose()

    # The App's credentials.

    def app_jwt(self) -> str:
        """The App's own JWT, signed now."""
        now = self._clock()
        header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claims = {
            "iat": int((now - JWT_SKEW).timestamp()),
            "exp": int((now + JWT_LIFETIME).timestamp()),
            "iss": self._app_id,
        }
        signing = f"{header}.{_b64(json.dumps(claims).encode())}"
        signature = self._private_key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing}.{_b64(signature)}"

    async def installation_token(self, installation: str) -> SecretStr:
        """The token of `installation`: the one held while it has more than
        `TOKEN_MARGIN` left, else a new one."""
        async with self._minting:
            held = self._tokens.get(installation)
            if held is not None and self._clock() < held.expires_at - TOKEN_MARGIN:
                return held.value
            answer = await self._call(
                "POST",
                f"{self._api}/app/installations/{installation}/access_tokens",
                bearer=SecretStr(self.app_jwt()),
                doing=f"a token for installation {installation}",
            )
            try:
                token = _Token(
                    value=SecretStr(str(answer["token"])),
                    expires_at=datetime.fromisoformat(str(answer["expires_at"])),
                )
            except KeyError, ValueError, TypeError:
                raise ProviderUnavailable("the forge answered no token") from None
            self._tokens[installation] = token
            log.info("forge: a token for installation %s, until %s", installation, token.expires_at)
            return token.value

    async def _installation_of(self, owner: str, repo: str) -> str:
        answer = await self._call(
            "GET",
            f"{self._api}/repos/{owner}/{repo}/installation",
            bearer=SecretStr(self.app_jwt()),
            doing=f"the installation of {owner}/{repo}",
        )
        try:
            return str(answer["id"])
        except KeyError, TypeError:
            raise ProviderUnavailable("the forge named no installation") from None

    async def _on(self, owner: str, repo: str) -> SecretStr:
        """The token of the installation that holds `owner/repo`."""
        return await self.installation_token(await self._installation_of(owner, repo))

    # Deliveries and grants.

    def verify_delivery(
        self, payload: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProvidedEvent | Acknowledged:
        return read_delivery(
            payload, headers, self._webhook_secret.get_secret_value(), self._account, now
        )

    async def verify_installation(self, grant: str, now: datetime) -> str:
        try:
            query = parse_qs(grant.lstrip("?"), strict_parsing=True)
        except ValueError:
            raise DeliveryRefused("the grant is not the setup redirect's query") from None
        ids, codes = query.get("installation_id", []), query.get("code", [])
        if len(ids) != 1 or not ids[0].isdigit() or len(codes) != 1:
            raise DeliveryRefused("the grant names no one installation and code")
        installation = ids[0]
        try:
            traded = await self._call(
                "POST",
                f"{self._web}/login/oauth/access_token",
                accept="application/json",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret.get_secret_value(),
                    "code": codes[0],
                },
                doing="the grant's code",
            )
        except ProviderRefused:
            raise DeliveryRefused("the forge did not confirm the grant's code") from None
        person = traded.get("access_token") if isinstance(traded, dict) else None
        if not isinstance(person, str) or not person:
            raise DeliveryRefused("the forge did not confirm the grant's code")
        for page in range(1, MAX_INSTALLATION_PAGES + 1):
            listed = await self._call(
                "GET",
                f"{self._api}/user/installations",
                bearer=SecretStr(person),
                params={"per_page": 100, "page": page},
                doing="the person's installations",
            )
            held = listed.get("installations") if isinstance(listed, dict) else None
            if not isinstance(held, list):
                raise ProviderUnavailable("the forge listed no installations")
            if any(isinstance(i, dict) and str(i.get("id")) == installation for i in held):
                return installation
            if len(held) < 100:
                break
        raise DeliveryRefused("the grant's installation is not one its person may reach")

    # Writes, each through the installation of the repository it names.

    async def post(self, address: str, text: str, mark: str | None = None) -> PostedMessage:
        named = ADDRESS.match(address)
        if named is None:
            raise ProviderRefused(f"{address} names no pull request or issue as owner/repo#n")
        owner, repo, number = named.groups()
        token = await self._on(owner, repo)
        answer = await self._call(
            "POST",
            f"{self._api}/repos/{owner}/{repo}/issues/{number}/comments",
            bearer=token,
            json={"body": marked(text, mark)},
            doing=f"a comment on {address}",
        )
        try:
            return PostedMessage(
                id=str(answer["id"]),
                address=address,
                text=text,
                provenance=REAL,
                posted_at=datetime.fromisoformat(str(answer["created_at"])),
                mark=mark,
            )
        except KeyError, ValueError, TypeError:
            raise ProviderUnavailable("the forge answered no comment") from None

    async def push(self, repository: str, ref: str, head: str, bundle: bytes) -> None:
        owner, repo = self._repository(repository)
        token = await self._on(owner, repo)
        await push_bundle(
            repository, ref, head, bundle, ("x-access-token", token.get_secret_value())
        )

    async def open_pull_request(
        self, repository: str, head: str, base: str | None, title: str, body: str
    ) -> OpenedPullRequest:
        owner, repo = self._repository(repository)
        token = await self._on(owner, repo)
        held = await self._open_of(owner, repo, head, token)
        if held is None:
            if base is None:
                about = await self._call(
                    "GET", f"{self._api}/repos/{owner}/{repo}", bearer=token, doing=repository
                )
                base = str(about.get("default_branch") or "") if isinstance(about, dict) else ""
                if not base:
                    raise ProviderUnavailable(f"the forge named no default branch of {repository}")
            try:
                held = await self._call(
                    "POST",
                    f"{self._api}/repos/{owner}/{repo}/pulls",
                    bearer=token,
                    json={"head": head, "base": base, "title": title, "body": body},
                    doing=f"the pull request of {head}",
                )
            except ProviderRefused:
                # Opened by a call that raced this one: answer it.
                held = await self._open_of(owner, repo, head, token)
                if held is None:
                    raise
        try:
            return OpenedPullRequest(
                id=f"{owner}/{repo}#{int(held['number'])}",
                url=str(held["html_url"]),
                repository=repository,
                head=head,
                base=str(held["base"]["ref"]),
                title=str(held["title"]),
                body=str(held.get("body") or ""),
                provenance=REAL,
            )
        except KeyError, ValueError, TypeError:
            raise ProviderUnavailable("the forge answered no pull request") from None

    async def _open_of(
        self, owner: str, repo: str, head: str, token: SecretStr
    ) -> dict[str, Any] | None:
        listed = await self._call(
            "GET",
            f"{self._api}/repos/{owner}/{repo}/pulls",
            bearer=token,
            params={"head": f"{owner}:{head}", "state": "open"},
            doing=f"the pull requests of {head}",
        )
        if not isinstance(listed, list):
            raise ProviderUnavailable("the forge listed no pull requests")
        return next((pull for pull in listed if isinstance(pull, dict)), None)

    def _repository(self, repository: str) -> tuple[str, str]:
        """The owner and the name of a repository as it is cloned from the
        forge's own host; `ProviderRefused` for any other."""
        parts = urlsplit(repository)
        named = REPOSITORY.match(parts.path)
        if parts.scheme != "https" or parts.netloc != self._host or named is None:
            raise ProviderRefused(f"{repository} is not a repository of {self._web}")
        return named.group(1), named.group(2)

    async def _call(
        self,
        method: str,
        url: str,
        *,
        doing: str,
        bearer: SecretStr | None = None,
        accept: str = "application/vnd.github+json",
        **kwargs: Any,
    ) -> Any:
        """One call, its answer's JSON. A refused key, a limit, a server
        error, or no answer is unavailable; any other refusal is refused.
        Neither names a credential."""
        headers = {"Accept": accept, "X-GitHub-Api-Version": API_VERSION}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer.get_secret_value()}"
        try:
            response = await self._http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as failed:
            kind = type(failed).__name__
            raise ProviderUnavailable(f"the forge did not answer {doing}: {kind}") from None
        if response.status_code >= 400:
            _refusal(response, doing)
        try:
            return response.json()
        except ValueError:
            raise ProviderUnavailable(f"the forge's answer to {doing} is not JSON") from None


def _refusal(response: httpx.Response, doing: str) -> NoReturn:
    status = response.status_code
    limited = status == 429 or (
        status == 403 and response.headers.get("x-ratelimit-remaining") == "0"
    )
    if status == 401 or limited or status >= 500:
        raise ProviderUnavailable(f"the forge answered {status} to {doing}")
    try:
        said = response.json().get("message")
    except ValueError, AttributeError:
        said = None
    raise ProviderRefused(f"the forge refused {doing} ({status}): {said or 'no message'}")
