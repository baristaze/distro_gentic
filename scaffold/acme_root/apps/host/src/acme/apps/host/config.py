"""Where a host finds the platform, its own credential, and its owner's
ceilings. Everything comes from the environment or from files on the host.
What every claimant reads, the host reads as the claimant kit does, under
the prefix `ACME` and the kind `host`: `ACME_API_URL`, `ACME_HOST_HOME`
(default `~/.config/acme-host`), which holds the host's `credential.json`
and the owner's `ceilings.toml`, `ACME_HOST_NAME`, the name it enrolls
under, and `ACME_ENROLLMENT_TOKEN`, read once at its first start. Its own
are `ACME_HOST_WORKSPACE_USER`, the dedicated user a bare-directory
workspace runs as, the image a container workspace runs, how long a pull of
it may take, and `ACME_HOST_SNAPSHOTS`, the store its workspaces' snapshots
and its tenants' bases are kept in (default `snapshots` under its home),
which hosts of a pool may share. `ACME_HOST_MACHINE_SEED` names the seed of
a machine of the platform's cloud pool: set, the host runs as that machine's
(`machine.py`), takes where the platform answers and its one-use key from
the seed, and makes its workspace under `ACME_HOST_MACHINE_WORKSPACE`
(default `/workspace`). Nothing the platform answers changes any of them."""

import os
from dataclasses import dataclass
from pathlib import Path

from acme.apps.host.seed import read_seed
from acme.apps.host.snapshots import STORE_FOLDER
from acme.client.claimant.credential import BadSetting
from acme.client.claimant.settings import ClaimantSettings, claimant_env

ENV_PREFIX = "ACME"
KIND = "host"
DEFAULT_IMAGE = "python:3.14"
"""The image a container workspace runs unless its owner names another: the
engine's own default, which holds Python and `git`."""
CEILINGS_FILE = "ceilings.toml"
SECRETS_FILE = "secrets"
RECORDS_FOLDER = "records"


@dataclass(frozen=True, kw_only=True)
class Settings(ClaimantSettings):
    workspace_user: str | None
    agent_workspace_image: str = DEFAULT_IMAGE
    pull_timeout_seconds: float = 900.0
    max_clock_skew_seconds: float = 60.0
    snapshot_store: Path | None = None  # None: `snapshots` under its home
    machine_seed: Path | None = None  # set: a machine of the cloud pool
    machine_workspace: Path = Path("/workspace")

    @property
    def machine(self) -> bool:
        """Whether the host runs in a machine the cloud pool started."""
        return self.machine_seed is not None

    @property
    def snapshots_path(self) -> Path:
        """The store its workspaces' snapshots are kept in, inside its
        owner's wall: owner-only, never sent to the platform."""
        return self.snapshot_store or self.home / STORE_FOLDER

    @property
    def ceilings_path(self) -> Path:
        return self.home / CEILINGS_FILE

    @property
    def secrets_path(self) -> Path:
        """The host's own secret store, owner-only, keyed by tenant first:
        `org/<org_id>/<name>=value` lines."""
        return self.home / SECRETS_FILE

    @property
    def records_path(self) -> Path:
        """Where its transport records how each command ended."""
        return self.home / RECORDS_FOLDER


def _seconds(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not value > 0:
        raise BadSetting(f"{name} is a number of seconds above zero, not {raw!r}")
    return value


def settings_from_env() -> Settings:
    claimant = claimant_env(ENV_PREFIX, KIND)
    seed = os.environ.get("ACME_HOST_MACHINE_SEED") or None
    if seed is not None:
        # A machine's seed says where the platform answers, and holds the
        # key its host trades once.
        seeded = read_seed(Path(seed))
        if seeded is not None:
            claimant["api_url"], claimant["enrollment_token"] = seeded
    return Settings(
        **claimant,
        workspace_user=os.environ.get("ACME_HOST_WORKSPACE_USER") or None,
        agent_workspace_image=os.environ.get("ACME_HOST_WORKSPACE_IMAGE") or DEFAULT_IMAGE,
        pull_timeout_seconds=_seconds("ACME_HOST_PULL_TIMEOUT_SECONDS", 900.0),
        snapshot_store=Path(os.environ["ACME_HOST_SNAPSHOTS"])
        if os.environ.get("ACME_HOST_SNAPSHOTS")
        else None,
        machine_seed=None if seed is None else Path(seed),
        machine_workspace=Path(os.environ.get("ACME_HOST_MACHINE_WORKSPACE") or "/workspace"),
    )
