"""A tiny project in the platform's shape for the distro-check tests, and a way to run the CLI on one.

`write_project` builds a product named `acme` with the parts the rules
read: the settings of the cloud's processes, a database's and a
provider key's among them, a bounded metric, the client of the gateway,
and a workspace host that imports only the client and reads only its
own variables. Every rule passes on it. Each test adds, overrides, or
drops the files its rule reads. `check` runs `acme.distro_check.cli.main`
on the tree and returns the exit status and what it printed.
"""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from acme.distro_check.cli import main

PYPROJECT = '[tool.distro-check]\npackage = "acme"\n'
ADR = "docs/adr/3001-the-legacy-host-imports-the-om.md"
HOST = "apps/host/src/acme/apps/host"
CONFIG = f"{HOST}/config.py"
AGENT = f"{HOST}/agent.py"
OBSERVABILITY = "infra/src/acme/infra/observability.py"

BASE: dict[str, str] = {
    "om/src/acme/om/__init__.py": "",
    "om/src/acme/om/work.py": "def requeue_stale() -> int:\n    return 0\n",
    # the cloud's settings: a database's, and a provider's key as a secret
    "om/src/acme/om/storage/__init__.py": "",
    "om/src/acme/om/storage/settings.py": (
        "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
        "class StorageSettings(BaseSettings):\n"
        '    model_config = SettingsConfigDict(env_prefix="ACME_", extra="ignore")\n\n'
        '    database_url: str = "postgresql://acme:acme@127.0.0.1/acme"\n'
        "    statement_seconds: float = 10.0\n"
    ),
    "integrations/src/acme/integrations/__init__.py": "",
    "integrations/src/acme/integrations/settings.py": (
        "from pydantic import Field, SecretStr\nfrom pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
        "class IntegrationsSettings(BaseSettings):\n"
        '    model_config = SettingsConfigDict(env_prefix="ACME_")\n\n'
        "    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)\n"
        '    model_providers: str = "none"\n'
    ),
    "workers/maintenance/src/acme/workers/maintenance/__init__.py": "",
    "workers/maintenance/src/acme/workers/maintenance/settings.py": (
        "from acme.integrations.settings import IntegrationsSettings\n"
        "from acme.om.storage.settings import StorageSettings\n\n\n"
        "class MaintenanceSettings(StorageSettings, IntegrationsSettings):\n"
        "    sweep_seconds: float = 30.0\n"
    ),
    "workers/maintenance/src/acme/workers/maintenance/loop.py": (
        "class WorkerLoop:\n    async def sweep(self) -> None:\n        pass\n"
    ),
    # a metric with bounded labels
    "infra/src/acme/infra/__init__.py": "",
    OBSERVABILITY: (
        "from prometheus_client import Counter, Gauge\n\n"
        'HTTP = Counter("acme_http_total", "Requests", ["route", "method", "status"])\n'
        'HOSTS = Gauge("acme_hosts", "Hosts by pool", labelnames=("host_pool", "plan_tier"))\n'
    ),
    # the client of the gateway, and a host that reaches the platform through it alone
    "clients/python/src/acme/client/__init__.py": "",
    "clients/python/src/acme/client/client.py": "class ApiClient:\n    pass\n",
    f"{HOST}/__init__.py": "",
    CONFIG: (
        '"""Reads `ACME_API_URL`, never `ACME_DATABASE_URL`."""\n\n'
        "import os\n\n\n"
        "def api_url() -> str:\n"
        '    return os.environ.get("ACME_API_URL", "http://127.0.0.1:8000")\n'
    ),
    AGENT: (
        "from typing import TYPE_CHECKING\n\n"
        "from acme.apps.host.config import api_url\n"
        "from acme.client.client import ApiClient\n\n"
        "from . import config\n\n"
        "if TYPE_CHECKING:\n    from acme.client import client\n\n\n"
        "def start() -> ApiClient:\n    api_url()\n    config.api_url()\n    return ApiClient()\n"
    ),
    ADR: (
        "# 3001. The legacy host imports the OM\n\nDate: 2026-10-02\n\n"
        "## Context\n\nAn old host.\n\n## Decision\n\nIt stays.\n"
    ),
}


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_project(
    root: Path, files: Mapping[str, str | None] | None = None, *, pyproject: str | None = PYPROJECT
) -> Path:
    """Write the base tree under `root`, then `files` over it; a `None` text drops a base file."""
    if pyproject is not None:
        write(root, "pyproject.toml", pyproject)
    for rel, text in {**BASE, **(files or {})}.items():
        if text is not None:
            write(root, rel, text)
    return root


def check(root: Path, *args: str) -> tuple[int, str, str]:
    """Run the CLI on `root`; (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--root", str(root), *args])
    return code, out.getvalue(), err.getvalue()


def check_json(root: Path, *args: str) -> tuple[int, dict[str, Any]]:
    """Run the CLI with `--format json`; (exit status, the parsed report)."""
    code, out, err = check(root, "--format", "json", *args)
    assert out, err
    return code, json.loads(out)


def found(root: Path, rule: str) -> list[tuple[str, int, str]]:
    """(path, line, message) of every finding of one rule, running that rule alone."""
    _, report = check_json(root, "--rule", rule)
    return [(f["path"], f["line"], f["message"]) for f in report["findings"] if f["rule"] == rule]
