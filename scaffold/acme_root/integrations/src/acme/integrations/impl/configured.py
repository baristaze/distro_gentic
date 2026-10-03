"""The integrations root that picks each provider from settings, and the
root over providers a caller already built. A twin is refused in a
deployed environment, the way the infra root refuses a local backend; the
caller says whether the environment is one, from the settings it booted
with."""

from collections.abc import Mapping
from datetime import timedelta

import httpx
from cryptography.exceptions import UnsupportedAlgorithm

from acme.integrations.events import INTEGRATIONS, IntegrationAbsentImpl, IntegrationInterface
from acme.integrations.events.github import GitHubImpl, load_private_key
from acme.integrations.events.slack import SlackImpl
from acme.integrations.events.slack_wire import CHAT
from acme.integrations.events.twin import FORGE, IntegrationTwinImpl
from acme.integrations.exceptions import ProviderUnavailable, UnsafeIntegration
from acme.integrations.identity import IdentityProviderInterface
from acme.integrations.identity.absent import IdentityProviderAbsentImpl
from acme.integrations.identity.twin import IdentityProviderTwinImpl
from acme.integrations.identity.workos import IdentityProviderWorkOSImpl
from acme.integrations.model_providers import ModelProvidersInterface
from acme.integrations.model_providers.anthropic import ModelProviderAnthropicImpl
from acme.integrations.model_providers.openai import ModelProviderOpenAIImpl
from acme.integrations.model_providers.registry import (
    ModelProvidersOverImpl,
    absent_model_providers,
    scripted_model_providers,
)
from acme.integrations.model_providers.scripted import read_script
from acme.integrations.model_providers.types import ProviderName
from acme.integrations.root import IntegrationsInterface
from acme.integrations.settings import IntegrationsSettings


def refuse_unsafe(settings: IntegrationsSettings, environment: str, deployed: bool) -> None:
    """A twin in a deployed environment is refused at boot, naming the setting."""
    if deployed and settings.identity_provider == "twin":
        raise UnsafeIntegration(
            f"ACME_IDENTITY_PROVIDER=twin is refused when ACME_ENVIRONMENT={environment}"
        )
    if deployed and settings.model_providers == "scripted":
        raise UnsafeIntegration(
            f"ACME_MODEL_PROVIDERS=scripted is refused when ACME_ENVIRONMENT={environment}"
        )
    if deployed and settings.integrations == "twin":
        raise UnsafeIntegration(
            f"ACME_INTEGRATIONS=twin is refused when ACME_ENVIRONMENT={environment}"
        )
    if deployed and settings.forge_integration == "twin":
        raise UnsafeIntegration(
            f"ACME_FORGE_INTEGRATION=twin is refused when ACME_ENVIRONMENT={environment}"
        )
    if deployed and settings.chat_integration == "twin":
        raise UnsafeIntegration(
            f"ACME_CHAT_INTEGRATION=twin is refused when ACME_ENVIRONMENT={environment}"
        )
    if deployed and settings.forge_twin_username:
        raise UnsafeIntegration(
            f"ACME_FORGE_TWIN_USERNAME is refused when ACME_ENVIRONMENT={environment}"
        )
    if deployed and settings.forge_twin_password is not None:
        raise UnsafeIntegration(
            f"ACME_FORGE_TWIN_PASSWORD is refused when ACME_ENVIRONMENT={environment}"
        )


def integrations_for(settings: IntegrationsSettings) -> dict[str, IntegrationInterface]:
    """Each integration the platform names, from settings: the forge and the
    chat each as its own setting says, else as `integrations` does. Each is
    its system's client, its twin, or the absent one, which refuses every
    call as unavailable. The forge's twin writes what is pushed to the
    repository, so a session's branch and its snapshots are there for its
    next loop, with the credential its settings give it where the repository
    asks one."""
    built: dict[str, IntegrationInterface] = {
        name: IntegrationTwinImpl(name)
        if settings.integrations == "twin"
        else IntegrationAbsentImpl(name)
        for name in INTEGRATIONS
    }
    forge = settings.forge_integration or settings.integrations
    if forge == "github":
        built[FORGE] = github_for(settings)
    elif forge == "twin":
        built[FORGE] = IntegrationTwinImpl(
            FORGE, writes=True, credential=forge_twin_credential(settings)
        )
    else:
        built[FORGE] = IntegrationAbsentImpl(FORGE)
    chat = settings.chat_integration or settings.integrations
    if chat == "slack":
        built[CHAT] = slack_for(settings)
    elif chat == "twin":
        built[CHAT] = IntegrationTwinImpl(CHAT)
    else:
        built[CHAT] = IntegrationAbsentImpl(CHAT)
    return built


def _unset(named: dict[str, object]) -> str | None:
    """What a client lacks, by the settings it reads; None when it has all."""
    missing = [name for name, value in named.items() if not value]
    return f"{', '.join(missing)} not set" if missing else None


def github_for(settings: IntegrationsSettings) -> IntegrationInterface:
    """The forge as a GitHub App, or absent, naming what it lacks: a client
    that cannot tell the platform's own account would wake a session with
    each of its own acts."""
    missing = _unset(
        {
            "ACME_GITHUB_APP_ID": settings.github_app_id,
            "ACME_GITHUB_PRIVATE_KEY": settings.github_private_key,
            "ACME_GITHUB_WEBHOOK_SECRET": settings.github_webhook_secret,
            "ACME_GITHUB_CLIENT_ID": settings.github_client_id,
            "ACME_GITHUB_CLIENT_SECRET": settings.github_client_secret,
            "ACME_GITHUB_ACCOUNT": settings.github_account,
        }
    )
    key, secret, client = (
        settings.github_private_key,
        settings.github_webhook_secret,
        settings.github_client_secret,
    )
    if missing is not None or key is None or secret is None or client is None:
        return IntegrationAbsentImpl(FORGE, missing)
    try:
        private_key = load_private_key(key.get_secret_value())
    except ValueError, TypeError, UnsupportedAlgorithm:
        return IntegrationAbsentImpl(FORGE, "ACME_GITHUB_PRIVATE_KEY is no RSA private key")
    return GitHubImpl(
        http=httpx.AsyncClient(timeout=settings.github_timeout_seconds),
        app_id=settings.github_app_id,
        private_key=private_key,
        webhook_secret=secret,
        client_id=settings.github_client_id,
        client_secret=client,
        account=settings.github_account,
        api_url=settings.github_api_url,
        web_url=settings.github_web_url,
    )


def slack_for(settings: IntegrationsSettings) -> IntegrationInterface:
    """The chat as a Slack app, or absent, naming what it lacks, as the
    forge's client is."""
    missing = _unset(
        {
            "ACME_SLACK_BOT_TOKEN": settings.slack_bot_token,
            "ACME_SLACK_SIGNING_SECRET": settings.slack_signing_secret,
            "ACME_SLACK_CLIENT_ID": settings.slack_client_id,
            "ACME_SLACK_CLIENT_SECRET": settings.slack_client_secret,
            "ACME_SLACK_ACCOUNT": settings.slack_account,
        }
    )
    token, secret, client = (
        settings.slack_bot_token,
        settings.slack_signing_secret,
        settings.slack_client_secret,
    )
    if missing is not None or token is None or secret is None or client is None:
        return IntegrationAbsentImpl(CHAT, missing)
    return SlackImpl(
        http=httpx.AsyncClient(timeout=settings.slack_timeout_seconds),
        bot_token=token,
        signing_secret=secret,
        client_id=settings.slack_client_id,
        client_secret=client,
        account=settings.slack_account,
        api_url=settings.slack_api_url,
    )


def forge_twin_credential(settings: IntegrationsSettings) -> tuple[str, str] | None:
    """The user and the password the forge's twin pushes with; none while
    the password is unset."""
    if settings.forge_twin_password is None:
        return None
    return settings.forge_twin_username, settings.forge_twin_password.get_secret_value()


def model_providers_for(settings: IntegrationsSettings) -> ModelProvidersInterface:
    """Each provider's adapter, from settings. A live adapter with no platform
    key still serves a call that carries its own credential."""
    if settings.model_providers == "scripted":
        script = None if settings.model_script is None else read_script(settings.model_script)
        return scripted_model_providers(
            script, pace=timedelta(seconds=settings.model_script_pace_seconds)
        )
    if settings.model_providers == "live":
        timeout = timedelta(seconds=settings.model_timeout_seconds)
        return ModelProvidersOverImpl(
            {
                ProviderName.ANTHROPIC: ModelProviderAnthropicImpl(
                    http=httpx.AsyncClient(timeout=settings.model_timeout_seconds),
                    api_key=settings.anthropic_api_key,
                    base_url=settings.anthropic_base_url,
                    timeout=timeout,
                ),
                ProviderName.OPENAI: ModelProviderOpenAIImpl(
                    http=httpx.AsyncClient(timeout=settings.model_timeout_seconds),
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    timeout=timeout,
                ),
            }
        )
    return absent_model_providers()


def identity_provider_for(settings: IntegrationsSettings) -> IdentityProviderInterface:
    if settings.identity_provider == "twin":
        return IdentityProviderTwinImpl()
    if settings.identity_provider == "workos":
        if not settings.workos_client_id:
            return IdentityProviderAbsentImpl("ACME_WORKOS_CLIENT_ID is not set")
        if settings.workos_api_key is None:
            return IdentityProviderAbsentImpl("ACME_WORKOS_API_KEY is not set")
        secret = settings.workos_webhook_secret
        return IdentityProviderWorkOSImpl(
            client_id=settings.workos_client_id,
            api_key=settings.workos_api_key.get_secret_value(),
            base_url=settings.workos_base_url,
            timeout=timedelta(seconds=settings.workos_timeout_seconds),
            webhook_secret=None if secret is None else secret.get_secret_value(),
        )
    return IdentityProviderAbsentImpl()


class IntegrationsOverImpl(IntegrationsInterface):
    """The root over providers already built: a test's twins, or the absent
    providers of a process that signs nobody in and calls no model."""

    def __init__(
        self,
        identity: IdentityProviderInterface,
        model_providers: ModelProvidersInterface,
        integrations: Mapping[str, IntegrationInterface] | None = None,
    ) -> None:
        self._identity = identity
        self._model_providers = model_providers
        self._integrations = dict(integrations or {})

    def get_identity_provider(self) -> IdentityProviderInterface:
        return self._identity

    def get_model_providers(self) -> ModelProvidersInterface:
        return self._model_providers

    def get_integration(self, name: str) -> IntegrationInterface:
        held = self._integrations.get(name)
        if held is None:
            raise ProviderUnavailable(f"no {name} integration is configured")
        return held

    def describe(self) -> list[str]:
        held = [integration.describe() for integration in self._integrations.values()]
        return [self._identity.describe(), *self._model_providers.describe(), *held]

    async def start(self) -> None:
        await self._identity.start()
        await self._model_providers.start()
        for integration in self._integrations.values():
            await integration.start()

    async def close(self) -> None:
        await self._identity.close()
        await self._model_providers.close()
        for integration in self._integrations.values():
            await integration.close()


def absent_integrations() -> IntegrationsInterface:
    """The root of a process that signs nobody in and calls no model."""
    return IntegrationsOverImpl(IdentityProviderAbsentImpl(), absent_model_providers())


class IntegrationsConfiguredImpl(IntegrationsOverImpl):
    def __init__(self, settings: IntegrationsSettings, environment: str, deployed: bool) -> None:
        refuse_unsafe(settings, environment, deployed)
        super().__init__(
            identity_provider_for(settings),
            model_providers_for(settings),
            integrations_for(settings),
        )
