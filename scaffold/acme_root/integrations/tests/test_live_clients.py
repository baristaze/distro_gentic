"""The forge's and the chat's clients against the real systems, by hand:
`make test-live`, with the settings of a GitHub App and a Slack app in
`.env`. Never a gate; each test is skipped without its settings."""

import httpx
import pytest

from acme.integrations.events.github import GitHubImpl
from acme.integrations.impl.configured import github_for
from acme.integrations.settings import IntegrationsSettings

pytestmark = pytest.mark.live


async def test_the_apps_jwt_is_the_apps_at_github() -> None:
    settings = IntegrationsSettings()
    forge = github_for(settings)
    if not isinstance(forge, GitHubImpl):
        pytest.skip(f"no GitHub App: {forge.describe()}")
    async with httpx.AsyncClient(timeout=settings.github_timeout_seconds) as http:
        answered = await http.get(
            f"{settings.github_api_url}/app",
            headers={
                "Authorization": f"Bearer {forge.app_jwt()}",
                "Accept": "application/vnd.github+json",
            },
        )
    await forge.close()
    assert answered.status_code == 200
    assert str(answered.json()["id"]) == settings.github_app_id


async def test_the_bot_token_is_the_platforms_account_at_slack() -> None:
    settings = IntegrationsSettings()
    if settings.slack_bot_token is None or not settings.slack_account:
        pytest.skip("no Slack app: ACME_SLACK_BOT_TOKEN or ACME_SLACK_ACCOUNT is not set")
    token = settings.slack_bot_token.get_secret_value()
    async with httpx.AsyncClient(timeout=settings.slack_timeout_seconds) as http:
        answered = await http.post(
            f"{settings.slack_api_url}/auth.test", headers={"Authorization": f"Bearer {token}"}
        )
    assert answered.json().get("user_id") == settings.slack_account
