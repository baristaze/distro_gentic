"""The host as a person's own client runs it: serving the workspace of one
session of theirs from the machine the client runs on, for as long as the
client runs.

The client asks the platform for a one-use key for the session
(`ApiClient.issue_client_key`), which only the person who started a session
whose workspace is local is issued. The host trades it, once, for a host's
credential of the session's local pool of one, as a VM of the cloud pool
trades its key: it is handed the work of that session's tree, the session,
its sub-agents, and the instances their checks ask for, and no other's. It
is the host program's own claim loop, made as `acme-host run` makes it
(`main.host_agent`), over the host's own transports and workspaces, and held
to the owner's `ceilings.toml` in the host's home: the exec relay, the
ceilings, and every wall stay one. A machine whose owner wrote no ceilings
serves nothing.

Its credential lives in a home of its own, a temporary folder only its user
reads, which goes as it stops. As it stops it ends its host, so the session's
next workspace call waits on the resource at once, until a client serves it
again; the next client the person starts ends any host that served before."""

import contextlib
import logging
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from acme.apps.host import main
from acme.apps.host.agent import HostAgent
from acme.apps.host.config import Settings, settings_from_env
from acme.apps.host.probe import Misconfigured
from acme.client.claimant.credential import BadSetting
from acme.client.claimant.enrollment import ClientFactory, CredentialRefused, NotEnrolled
from acme.client.transport import WIRE_FAILURES, ApiError

log = logging.getLogger(__name__)

STOPS = (BadSetting, Misconfigured, NotEnrolled, CredentialRefused, ApiError)
"""What stops a client's host, before it serves or while it does, for its
person to read: a setting or a ceilings file of the host's that is wrong, a
probe that failed, a key the platform refused, or a host it ended, as when
the person's next client took the session over."""

UNENDED = (ApiError, CredentialRefused, *WIRE_FAILURES)
"""What leaves a host unended as it stops: the platform refused or did not
answer, and the host falls silent instead."""

Build = Callable[[Settings, ClientFactory | None], HostAgent]
"""Makes the host a client runs, not yet started (`main.host_agent`)."""


def serving_settings(host: Settings, api_url: str, key: str, home: Path) -> Settings:
    """What the host a client runs reads: the host's own settings, with the
    platform the client calls, the session's one-use key in the place of an
    enrollment token, and `home` for its credential; its owner's ceilings,
    secrets, and snapshots stay in the host's home. Never a VM's."""
    return replace(
        host,
        api_url=api_url.rstrip("/"),
        home=home,
        enrollment_token=key,
        owner_home=host.owners,
        vm_seed=None,
    )


async def serve_session(
    api_url: str,
    key: str,
    *,
    client_for: ClientFactory | None = None,
    build: Build | None = None,
    host: Settings | None = None,
) -> None:
    """Serves the session `key` was issued for until cancelled: probes,
    trades the key, then beats, rotates, and claims as any host does, and
    ends its host as it stops. A failed probe, a missing ceilings file, or
    a refused key raises before anything is claimed (`STOPS`). It is made
    by `build`, else as `acme-host run` makes it, from `host`, else the
    host's own environment."""
    owner = host or settings_from_env()
    with tempfile.TemporaryDirectory(prefix="acme-serve-") as folder:
        settings = serving_settings(owner, api_url, key, Path(folder))
        agent = (build or main.host_agent)(settings, client_for)
        await agent.start()
        try:
            await main.serve(agent, settings)
        finally:
            await end(agent)


async def end(agent: HostAgent) -> None:
    """Ends the host at the platform as it stops; a platform it cannot reach
    then ends it once it falls silent."""
    with contextlib.suppress(*UNENDED):
        async with agent.client() as client:
            await client.end_host()
        log.info("this client's host ended: the session waits for the next one")
