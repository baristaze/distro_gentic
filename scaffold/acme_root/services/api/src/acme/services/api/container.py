"""Every process boots the same way: settings, then logging, the process name,
the trust store, error reporting, and tracing, then storage, infra, the managers,
and the services, in that order. Routers resolve them per request from this one
object."""

import logging
from datetime import timedelta

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.observability import (
    configure_error_reporting,
    configure_logging,
    configure_tracing,
    name_process,
)
from acme.infra.root import InfraInterface
from acme.infra.trust import install_trust_store
from acme.integrations.impl.configured import IntegrationsConfiguredImpl, absent_integrations
from acme.integrations.root import IntegrationsInterface
from acme.om.agents.types.kind import AgentKind
from acme.om.automations.root import build_automations
from acme.om.billing.root import build_money_gate, refuse_open_money
from acme.om.intake.root import build_intake
from acme.om.knowledge.root import build_knowledge
from acme.om.notifications.root import build_notifications
from acme.om.platform_agents.catalog import PlatformAgents
from acme.om.platform_agents.settings import shipped_agents
from acme.om.playbooks.root import PlaybooksLayer
from acme.om.root import (
    LOCAL,
    Managers,
    PlatformPorts,
    TenancyOperatorOptions,
    TenancyOptions,
    build_managers,
)
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.root import StorageInterface
from acme.om.trust.root import build_trust_operator
from acme.om.watch.impl.manager import WatchOptions
from acme.om.watch.root import build_stream, build_watch
from acme.om.watch.stream import StreamServiceInterface
from acme.om.workspaces.impl.executor import ExecutorOptions
from acme.services.api.gateway.ratelimit import RateLimit, RateLimitOptions, RefusedAddresses
from acme.services.api.services import ServicesInterface
from acme.services.api.services.impl.root import build_services
from acme.services.api.settings import ApiSettings

log = logging.getLogger(__name__)

_booted = False


def boot(settings: ApiSettings) -> None:
    """Settings first, then logging, the process name, the trust store, error
    reporting, and tracing. Every entry point calls it before it builds a
    container; it runs once per process.

    Naming the process is a step of its own, second: every line this boot
    writes carries the service and the environment, and a boot that configures
    no error reporting still names them."""
    global _booted
    if _booted:
        return
    configure_logging(settings.log_level, settings.log_json)
    name_process(settings.service_name, settings.environment)
    install_trust_store()
    configure_error_reporting(
        settings.sentry_dsn, settings.environment, settings.service_name, settings.version
    )
    configure_tracing(
        settings.otel_endpoint,
        settings.service_name,
        timedelta(seconds=settings.otel_timeout_seconds),
    )
    _booted = True


def totp_key(settings: ApiSettings) -> str | None:
    key = settings.totp_encryption_key
    return None if key is None else key.get_secret_value()


def tenancy_options(settings: ApiSettings) -> TenancyOptions:
    return TenancyOptions(
        login_ttl=timedelta(seconds=settings.login_lifetime_seconds),
        session_ttl=timedelta(seconds=settings.session_lifetime_seconds),
        session_idle_ttl=timedelta(seconds=settings.session_idle_lifetime_seconds),
        sign_in_free_failures=settings.sign_in_free_failures,
        sign_in_delay_base=timedelta(seconds=settings.sign_in_delay_base_seconds),
        sign_in_delay_cap=timedelta(seconds=settings.sign_in_delay_cap_seconds),
        operator_token_ttl=timedelta(seconds=settings.operator_token_max_lifetime_seconds),
        totp_encryption_key=totp_key(settings),
        sign_in_redirect_uris=tuple(settings.sign_in_redirect_uris),
        sign_out_return_uris=tuple(settings.sign_out_return_uris),
        dev_sign_in=settings.dev_sign_in_enabled,
        invitation_ttl_days=settings.invitation_lifetime_days,
    )


def operator_options(settings: ApiSettings) -> TenancyOperatorOptions:
    return TenancyOperatorOptions(
        operator_token_ttl=timedelta(seconds=settings.operator_token_max_lifetime_seconds),
        totp_encryption_key=totp_key(settings),
    )


def rate_limit_options(settings: ApiSettings) -> RateLimitOptions:
    return RateLimitOptions(
        login=RateLimit(
            limit=settings.login_rate_limit,
            window=timedelta(seconds=settings.login_rate_window_seconds),
        ),
        reads=RateLimit(
            limit=settings.credential_rate_limit_reads,
            window=timedelta(seconds=settings.credential_rate_window_seconds),
        ),
        writes=RateLimit(
            limit=settings.credential_rate_limit_writes,
            window=timedelta(seconds=settings.credential_rate_window_seconds),
        ),
        failed_authentications=RateLimit(
            limit=settings.failed_authentication_limit,
            window=timedelta(seconds=settings.failed_authentication_window_seconds),
        ),
    )


def postgres_storage(settings: ApiSettings) -> StorageInterface:
    """The storage root over the database the settings name: the one place a
    process of this service opens its pools."""
    return StoragePostgresImpl(
        settings.role_urls(),
        settings.role_pools(),
        system_urls=settings.system_role_urls(),
    )


def memory_storage() -> StorageInterface:
    """The storage root in memory, for a command that reads the app's shape
    and no data: the OpenAPI document is emitted over it."""
    return StorageMemoryImpl()


class AppContainer:
    def __init__(
        self,
        settings: ApiSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface,
        managers: Managers,
        services: ServicesInterface,
        rate_limits: RateLimitOptions,
        stream: StreamServiceInterface,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.integrations = integrations
        self.managers = managers
        self.services = services
        self.rate_limits = rate_limits
        # The stream service the live reads of this process come from.
        self.stream = stream
        # What the shared count said of each address that spent its budget of
        # failed authentications, until that window ends (ADR 0059).
        self.refused_addresses = RefusedAddresses()

    @classmethod
    def build(cls, settings: ApiSettings) -> AppContainer:
        return cls.over(
            settings,
            postgres_storage(settings),
            InfraConfiguredImpl(settings),
            IntegrationsConfiguredImpl(
                settings, settings.environment, settings.is_cloud_environment
            ),
            platform_agents=shipped_agents(settings, settings.environment),
        )

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: ApiSettings | None = None,
        integrations: IntegrationsInterface | None = None,
        *,
        agent_kinds: tuple[AgentKind, ...] = (),
        ports: PlatformPorts | None = None,
    ) -> AppContainer:
        settings = settings or ApiSettings.model_validate(
            {
                "_env_file": None,
                "environment": "test",
                "dev_sign_in_enabled": True,
            }
        )
        # No identity provider unless the test hands one in.
        integrations = integrations or absent_integrations()
        return cls.over(
            settings, storage, infra, integrations, agent_kinds=agent_kinds, ports=ports
        )

    @classmethod
    def over(
        cls,
        settings: ApiSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        integrations: IntegrationsInterface,
        *,
        agent_kinds: tuple[AgentKind, ...] = (),
        ports: PlatformPorts | None = None,
        platform_agents: PlatformAgents | None = None,
    ) -> AppContainer:
        """Managers, then services, over whichever roots the caller chose.
        `agent_kinds` are the product's: a session starts on one of them, and
        the session runner runs its loop with the same kinds. `ports` are the
        platform's ports the product sets, None each for the platform's own:
        billing's money gate, and the evidence's result gate. Outside
        `local`, a quiet null for any of them, or a budget gate that is not
        the money gate, is refused at boot. `platform_agents` ships the
        platform's agents beside the product's kinds: a deployed process
        reads them from its corpus root, and refuses to boot with none."""
        ports = ports or PlatformPorts()
        managers = build_managers(
            storage,
            infra,
            tenancy_options(settings),
            operator_options(settings),
            integrations,
            environment=settings.environment,
            agent_kinds=agent_kinds,
            platform_agents=platform_agents,
            budget_gate=ports.budget_gate or build_money_gate(storage),
            result_gate=ports.result_gate,
            executor=ports.executor,
            executor_options=ExecutorOptions(image=settings.workspace_image),
            work_product=ports.work_product,
            session_projects=ports.session_projects,
            workspace_projects=ports.workspace_projects,
        )
        refuse_open_money(settings.environment, managers)
        # Where a tenant connects a system, and where a person reads and
        # clears what waits on them.
        intake = build_intake(storage, managers, integrations=integrations)
        # The streams the runners write, read from the shared cache.
        stream = build_stream(infra, lambda: managers.events)
        watch = build_watch(managers, stream, WatchOptions(live_read_key=settings.live_read_key))
        services = build_services(
            managers,
            infra,
            integrations,
            timedelta(seconds=settings.realtime_head_max_age_seconds),
            watch,
            build_trust_operator(storage, infra),
            # Outside a local stack, a session starts in a project.
            project_required=settings.environment != LOCAL,
            intake=intake,
            automations=build_automations(
                storage, managers, project_required=settings.environment != LOCAL
            ),
            notifications=build_notifications(storage, managers, integrations, intake),
            # A person writes and reviews what sessions recall, and publishes
            # the playbooks they follow; the runner recalls and invokes them.
            knowledge=build_knowledge(storage, managers),
            playbooks=PlaybooksLayer(storage).build(managers),
        )
        return cls(
            settings,
            storage,
            infra,
            integrations,
            managers,
            services,
            rate_limit_options(settings),
            stream,
        )

    async def start(self) -> None:
        await self.infra.start()
        await self.integrations.start()
        chosen = [*self.infra.describe(), *self.integrations.describe()]
        log.info("%s started with %s", self.settings.service_name, ", ".join(chosen))
        if not self.integrations.get_identity_provider().configured:
            log.warning("no identity provider: every sign-in through one answers 503")
        if self.settings.dev_sign_in_enabled:
            log.warning("the local sign-in by address alone is on")
        if self.settings.totp_encryption_key is None:
            log.warning(
                "no TOTP encryption key: the operator plane refuses every enrolment "
                "and every sign-in that presents a code"
            )
        if self.settings.live_read_key is None:
            log.warning("no live-read key: every live read of a session is refused")

    async def close(self) -> None:
        await self.stream.close()
        await self.integrations.close()
        await self.infra.close()
        await self.storage.close()
