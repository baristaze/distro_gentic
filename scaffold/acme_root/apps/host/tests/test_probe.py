"""A host's startup: it fails there when it cannot reach what it needs, and
it advertises its machine and only the isolation modes whose probe
passed."""

import dataclasses
import getpass
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import typer
from host_support import Stack, failing, probes

from acme.apps.host.main import (
    EXIT_MISCONFIGURED,
    EXIT_REFUSED,
    EXIT_UNREACHABLE,
    _guarded,
    host_network,
)
from acme.apps.host.probe import Misconfigured, Probe, directory, proxy, startup
from acme.client.client import ApiClient, ApiError
from acme.client.types import IsolationMode
from acme.om.base import utcnow


async def test_a_host_advertises_only_the_modes_it_probed(api: Stack) -> None:
    async with api.client(None) as client:
        probed = await startup(probes(IsolationMode.container), client, 60)
    advertised = probed.advertisement
    assert advertised.isolation_modes == [IsolationMode.container]
    assert advertised.model_dump(mode="json")["capabilities"] == ["git"]
    assert advertised.os
    failed = {result.name for result in probed.results if not result.passed}
    assert failed == {"vm", "directory"}


async def test_a_host_that_probed_no_mode_advertises_none(api: Stack) -> None:
    async with api.client(None) as client:
        probed = await startup(probes(), client, 60)
    assert probed.advertisement.isolation_modes == []


async def test_a_misconfigured_host_fails_at_startup_and_says_why(api: Stack) -> None:
    broken_store = dataclasses.replace(probes(), trust_store=lambda: failing("trust_store"))
    async with api.client(None) as client:
        with pytest.raises(Misconfigured) as refused:
            await startup(broken_store, client, 60)
        assert [probe.name for probe in refused.value.failed] == ["trust_store"]
        # A clock two hours off the platform's.
        with pytest.raises(Misconfigured) as skewed:
            await startup(probes(), client, 60, now=lambda: utcnow() + timedelta(hours=2))
        assert [probe.name for probe in skewed.value.failed] == ["clock"]


async def test_a_host_that_cannot_reach_the_platform_fails_at_startup() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = ApiClient(
        "http://test", app="api", app_version="host@test", transport=httpx.MockTransport(refuse)
    )
    async with client:
        with pytest.raises(Misconfigured) as refused:
            await startup(probes(), client, 60)
    assert {probe.name for probe in refused.value.failed} == {"platform", "clock"}


def test_a_proxy_the_environment_names_is_a_url() -> None:
    assert proxy({}).passed
    assert proxy({"HTTPS_PROXY": "http://proxy.internal:3128"}).passed
    assert not proxy({"HTTPS_PROXY": "proxy.internal:3128"}).passed
    assert not proxy({"https_proxy": "ftp://proxy.internal"}).passed


def test_a_bare_directory_runs_only_as_a_dedicated_user() -> None:
    assert not directory(None).passed
    assert not directory("root").passed
    assert not directory(getpass.getuser()).passed
    assert not directory("no-such-user-on-this-machine").passed


def test_a_ca_file_the_host_cannot_read_stops_it_before_any_prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host reads its CA file once, as it starts, for every container it
    will prepare: one it cannot read stops it there, as a failed probe
    does, and no session's prepare ever meets it."""
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "absent.pem"))
    with pytest.raises(Misconfigured) as refused:
        host_network()
    assert [probe.name for probe in refused.value.failed] == ["trust_store"]


def _probe(name: str) -> Probe:
    return Probe(name, False, "failed")


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        # The platform down, or the clock not yet in step: it passes with time.
        (Misconfigured([_probe("platform"), _probe("clock")]), EXIT_UNREACHABLE),
        (Misconfigured([_probe("clock")]), EXIT_UNREACHABLE),
        (ApiError(503, "unavailable", "down", None), EXIT_UNREACHABLE),
        (ApiError(429, "too_many", "slow down", None), EXIT_UNREACHABLE),
        # What a person must fix.
        (Misconfigured([_probe("trust_store")]), EXIT_MISCONFIGURED),
        (Misconfigured([_probe("platform"), _probe("proxy")]), EXIT_MISCONFIGURED),
        (ApiError(401, "unauthorized", "token spent", None), EXIT_REFUSED),
        (ApiError(409, "conflict", "name taken", None), EXIT_REFUSED),
    ],
)
def test_a_start_that_fails_with_time_exits_to_be_restarted(raised: Exception, code: int) -> None:
    """The unit restarts the host on 4 and leaves it stopped on 1 and 5: a
    host started during an outage comes back on its own, and one a person
    must fix does not spin."""

    async def start() -> None:
        raise raised

    with pytest.raises(typer.Exit) as ended:
        _guarded(start())
    assert ended.value.exit_code == code
