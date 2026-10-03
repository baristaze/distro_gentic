"""The chat as a Slack app: Slack's Web API over `httpx`.

The client posts with the app's bot token, the platform's one account in
the workspace it was made in, and checks each delivery with the app's
signing secret (`slack_wire.py`). A tenant connects a workspace with the
code Slack hands the person who installed the app there: the code is
traded at Slack, and the workspace counts only when Slack names it and it
is the bot token's own, which Slack names once (`auth.test`): the client
posts with that token alone, so a workspace it cannot reach is refused.
What the trade answers besides the workspace, a token among it, is used
for nothing and kept nowhere (ADR 2020).

Slack answers most refusals with `200` and `ok: false`: an error that
says the key is refused is unavailable, any other is refused."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn

import httpx
from pydantic import SecretStr

from acme.integrations.events import (
    Acknowledged,
    IntegrationInterface,
    OpenedPullRequest,
    PostedMessage,
    Provenance,
    ProvidedEvent,
)
from acme.integrations.events.slack_wire import CHAT, MARK_EVENT, message_id, read_delivery
from acme.integrations.exceptions import DeliveryRefused, ProviderRefused, ProviderUnavailable

REAL: Provenance = "real"
KEY_REFUSED = frozenset(
    {
        "not_authed",
        "invalid_auth",
        "account_inactive",
        "token_revoked",
        "token_expired",
        "no_permission",
        "missing_scope",
        "ratelimited",
        "invalid_client_id",
        "bad_client_secret",
    }
)
"""The errors that say the platform's key, not the request, was refused."""


class SlackImpl(IntegrationInterface):
    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        bot_token: SecretStr,
        signing_secret: SecretStr,
        client_id: str,
        client_secret: SecretStr,
        account: str,
        api_url: str = "https://slack.com/api",
    ) -> None:
        self._http = http
        self._bot_token = bot_token
        self._signing_secret = signing_secret
        self._client_id = client_id
        self._client_secret = client_secret
        self._account = account
        self._api = api_url.rstrip("/")
        self._team: str | None = None

    @property
    def name(self) -> str:
        return CHAT

    @property
    def provenance(self) -> Provenance:
        return REAL

    def describe(self) -> str:
        return f"{CHAT}=slack account={self._account}"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        await self._http.aclose()

    def verify_delivery(
        self, payload: bytes, headers: Mapping[str, str], now: datetime
    ) -> ProvidedEvent | Acknowledged:
        return read_delivery(
            payload, headers, self._signing_secret.get_secret_value(), self._account, now
        )

    async def verify_installation(self, grant: str, now: datetime) -> str:
        if not grant or len(grant) > 500:
            raise DeliveryRefused("the grant is not a code")
        try:
            answer = await self._call(
                "oauth.v2.access",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret.get_secret_value(),
                    "code": grant,
                },
            )
        except ProviderRefused:
            raise DeliveryRefused("the chat did not confirm the grant's code") from None
        team = answer.get("team")
        workspace = team.get("id") if isinstance(team, dict) else None
        if not isinstance(workspace, str) or not workspace:
            raise DeliveryRefused("the chat named no workspace for the grant")
        reached = await self._bot_team()
        if workspace != reached:
            raise DeliveryRefused(
                f"workspace {workspace} is not {reached}, the one workspace the platform's "
                "bot token posts to"
            )
        return workspace

    async def _bot_team(self) -> str:
        """The workspace the bot token reaches, as Slack names it, asked once."""
        if self._team is None:
            team = (await self._call("auth.test", bearer=self._bot_token)).get("team_id")
            if not isinstance(team, str) or not team:
                raise ProviderUnavailable("the chat named no workspace for the bot token")
            self._team = team
        return self._team

    async def installation_of(self, target: str) -> str:
        raise ProviderRefused("the chat holds no repository")

    async def post(
        self, address: str, text: str, mark: str | None = None, *, installation: str | None = None
    ) -> PostedMessage:
        message: dict[str, Any] = {"channel": address, "text": text}
        if mark is not None:
            message["metadata"] = {"event_type": MARK_EVENT, "event_payload": {"mark": mark}}
        answer = await self._call("chat.postMessage", json=message, bearer=self._bot_token)
        try:
            ts = str(answer["ts"])
            return PostedMessage(
                id=message_id(str(answer["channel"]), ts),
                address=address,
                text=text,
                provenance=REAL,
                posted_at=datetime.fromtimestamp(float(ts), UTC),
                mark=mark,
            )
        except KeyError, ValueError, TypeError:
            raise ProviderUnavailable("the chat answered no message") from None

    async def push(
        self, repository: str, ref: str, head: str, bundle: bytes, *, installation: str
    ) -> None:
        raise ProviderRefused("the chat holds no repository")

    async def open_pull_request(
        self,
        repository: str,
        head: str,
        base: str | None,
        title: str,
        body: str,
        *,
        installation: str,
    ) -> OpenedPullRequest:
        raise ProviderRefused("the chat holds no repository")

    async def _call(
        self, method: str, *, bearer: SecretStr | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """One call of the Web API, its answer once it says `ok`. Neither
        failure names a credential."""
        headers = {}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer.get_secret_value()}"
        try:
            response = await self._http.post(f"{self._api}/{method}", headers=headers, **kwargs)
        except httpx.HTTPError as failed:
            kind = type(failed).__name__
            raise ProviderUnavailable(f"the chat did not answer {method}: {kind}") from None
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderUnavailable(f"the chat answered {response.status_code} to {method}")
        try:
            answer = response.json()
        except ValueError:
            raise ProviderUnavailable(f"the chat's answer to {method} is not JSON") from None
        if not isinstance(answer, dict) or answer.get("ok") is not True:
            _refusal(method, answer.get("error") if isinstance(answer, dict) else None)
        return answer


def _refusal(method: str, error: object) -> NoReturn:
    if error in KEY_REFUSED:
        raise ProviderUnavailable(f"the chat refused the platform's key for {method}: {error}")
    raise ProviderRefused(f"the chat refused {method}: {error or 'no error named'}")
