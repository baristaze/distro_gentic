"""The one settings object of the session runner.

The runner reads the same `.env` the other processes do, so its own knobs
carry a prefix of their own, `ACME_RUNNER_`: the maintenance worker's
`ACME_WORKER_*` and its metrics port never reach it, and two processes on
one host never bind one port."""

import os
import socket

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from acme.infra.impl.settings import InfraSettings
from acme.integrations.settings import IntegrationsSettings
from acme.om.placement.rules import DEFAULT_TIER, tier_lane
from acme.om.platform_agents.settings import PlatformAgentsSettings
from acme.om.storage.settings import StorageSettings


def default_runner_id() -> str:
    return f"session-runner-{socket.gethostname()}-{os.getpid()}"


class SessionRunnerSettings(
    StorageSettings, InfraSettings, IntegrationsSettings, PlatformAgentsSettings
):
    model_config = SettingsConfigDict(env_prefix="ACME_", env_file=".env", extra="ignore")

    service_name: str = "session-runner"
    version: str = "0.1.0"
    # The runner serves no HTTP but its metrics and its probe; containers
    # bind 0.0.0.0.
    metrics_host: str = "127.0.0.1"
    runner_metrics_port: int = 9465
    runner_id: str = Field(default_factory=default_runner_id)
    # The loop lane it claims from: a plan tier's, or a tenant's own
    # (`acme.om.placement.rules`). Each lane in use has runners of its own.
    runner_lane: str = tier_lane(DEFAULT_TIER)
    # Each is a count or a duration the claim loop divides or waits on, so
    # zero is a broken setting, refused at start, as the maintenance
    # worker's are. A loop runs for minutes, so a runner holds few at once;
    # its lease is renewed while the loop runs, and a runner that dies
    # leaves its loop to the next claim once the lease runs out.
    runner_capacity: int = Field(default=4, gt=0)
    runner_lease_seconds: int = Field(default=60, gt=0)
    runner_heartbeat_seconds: int = Field(default=10, gt=0)
    runner_sweep_seconds: int = Field(default=30, gt=0)
    runner_poll_seconds: int = Field(default=5, gt=0)
    # How long a workspace instance on this host that no run accounts for
    # stays before the sweep lets it go, its work pushed first.
    runner_workspace_grace_seconds: int = Field(default=300, gt=0)
