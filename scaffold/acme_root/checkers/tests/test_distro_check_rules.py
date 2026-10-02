"""distro-check's rules: each rule fires on a bad tree and stays quiet on the good one.

The base tree of `distro_check_fixtures` is clean under every rule, so
each test plants one breach and reads the rule that decides it.
"""

import pytest

pytest.importorskip("tomllib")

from distro_check_fixtures import (
    AGENT,
    CONFIG,
    HOST,
    OBSERVABILITY,
    PYPROJECT,
    check,
    found,
    write_project,
)


def test_the_base_tree_is_clean_under_every_rule(tmp_path):
    write_project(tmp_path)
    code, out, err = check(tmp_path)
    assert (code, err) == (0, ""), out
    assert out.startswith("distro-check ok: 3 rule(s)")


# --- PLC-10: a host reaches the platform through the client of the gateway alone

REACHING = (
    "import acme.om.work\n"
    "from acme.workers.maintenance.loop import WorkerLoop\n"
    "from acme import infra\n"
    "from ... import om\n\n\n"
    "def run() -> None:\n"
    "    from acme.integrations.settings import IntegrationsSettings\n"
    "    WorkerLoop()\n"
)


def test_plc10_a_host_that_imports_the_platforms_code_is_a_finding(tmp_path):
    write_project(tmp_path, {f"{HOST}/sweep.py": REACHING})
    hits = found(tmp_path, "PLC-10")
    assert [(path, line) for path, line, _ in hits] == [
        (f"{HOST}/sweep.py", n) for n in (1, 2, 3, 4, 8)
    ]
    assert [m.split(";")[0].rpartition(" ")[2] for _, _, m in hits] == [
        "acme.om.work",
        "acme.workers.maintenance.loop.WorkerLoop",
        "acme.infra",
        "acme.om",
        "acme.integrations.settings.IntegrationsSettings",
    ]
    assert hits[0][2].endswith("reaches the platform through acme.client alone")


def test_plc10_the_hosts_own_app_and_the_client_pass(tmp_path):
    write_project(tmp_path)
    assert found(tmp_path, "PLC-10") == []


def test_plc10_the_option_names_another_app_inside_the_wall(tmp_path):
    daemon = "apps/station_daemon/src/acme/apps/station_daemon"
    files = {
        f"{daemon}/__init__.py": "",
        f"{daemon}/main.py": "from acme.apps.host import config\n",
    }
    write_project(tmp_path, files)
    assert found(tmp_path, "PLC-10") == []
    option = (
        '\n[tool.distro-check.options.PLC-10]\nmodules = ["apps.host", "apps.station_daemon"]\n'
    )
    write_project(tmp_path, files, pyproject=PYPROJECT + option)
    assert [(p, line) for p, line, _ in found(tmp_path, "PLC-10")] == [(f"{daemon}/main.py", 1)]


def test_plc10_no_app_named_checks_nothing(tmp_path):
    option = "\n[tool.distro-check.options.PLC-10]\nmodules = []\n"
    write_project(tmp_path, {f"{HOST}/sweep.py": REACHING}, pyproject=PYPROJECT + option)
    assert found(tmp_path, "PLC-10") == []


# --- PLC-16: a host names none of the cloud's secrets

NAMING = (
    "import os\n\n\n"
    "def database() -> str:\n"
    '    return os.environ["ACME_DATABASE_URL"]\n\n\n'
    "def keys() -> list[str | None]:\n"
    '    return [os.getenv("acme_anthropic_api_key"), os.getenv("ANTHROPIC_API_KEY")]\n'
)
HOST_SETTINGS = (
    "from pydantic import Field\nfrom pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
    "class HostSettings(BaseSettings):\n"
    '    model_config = SettingsConfigDict(env_prefix="ACME_")\n\n'
    '    api_url: str = "http://127.0.0.1:8000"\n'
    '    database_url: str = ""\n'
    '    key: str = Field(default="", validation_alias="OPENAI_API_KEY")\n'
)


def test_plc16_a_host_that_names_a_cloud_secret_is_a_finding(tmp_path):
    write_project(tmp_path, {f"{HOST}/naming.py": NAMING, f"{HOST}/settings.py": HOST_SETTINGS})
    hits = found(tmp_path, "PLC-16")
    assert [(path.rpartition("/")[2], line) for path, line, _ in hits] == [
        ("naming.py", 5),
        ("naming.py", 9),
        ("naming.py", 9),
        ("settings.py", 9),
        ("settings.py", 10),
    ]
    messages = [m.split(";")[0] for _, _, m in hits]
    assert messages == [
        "names ACME_DATABASE_URL, the cloud's StorageSettings.database_url",
        "names acme_anthropic_api_key, the cloud's IntegrationsSettings.anthropic_api_key",
        "names ANTHROPIC_API_KEY, a model provider's key",
        "reads database_url from ACME_DATABASE_URL, the cloud's StorageSettings.database_url",
        "names OPENAI_API_KEY, a model provider's key",
    ]


CREDENTIALS = (
    "import os\n\n"
    'STORE = os.environ.get("ACME_S3_ACCESS_KEY"), os.environ.get("ACME_S3_SECRET_KEY")\n'
    'GITHUB = os.environ.get("ACME_SECRET_GITHUB_TOKEN")\n'
    'TENANTS = [v for k, v in os.environ.items() if k.startswith("ACME_SECRET_")]\n'
    'KMS = os.environ.get("ACME_KMS_KEY_ID")\n'
)


def test_plc16_a_credential_typed_as_a_string_and_the_secret_stores_variables_are_findings(
    tmp_path,
):
    write_project(tmp_path, {f"{HOST}/store.py": CREDENTIALS})
    hits = found(tmp_path, "PLC-16")
    assert [(line, m.split(",")[0]) for _, line, m in hits] == [
        (3, "names ACME_S3_ACCESS_KEY"),
        (3, "names ACME_S3_SECRET_KEY"),
        (4, "names ACME_SECRET_GITHUB_TOKEN"),
        (5, "names ACME_SECRET_"),
    ]
    assert "the cloud's InfraSettings.s3_secret_key;" in hits[1][2]
    assert all(
        "a variable of the cloud's secret store (ACME_SECRET_);" in m for _, _, m in hits[2:]
    )


def test_plc16_the_hosts_own_variables_and_its_docstrings_pass(tmp_path):
    write_project(tmp_path)
    assert found(tmp_path, "PLC-16") == []


def test_plc16_a_cloud_setting_that_holds_no_secret_and_an_inherited_prefix(tmp_path):
    files = {
        CONFIG: 'import os\n\nSWEEP = os.environ.get("ACME_SWEEP_SECONDS")\n',
        f"{HOST}/purge.py": 'import os\n\nPURGE = os.environ.get("ACME_DATABASE_PURGE_URL")\n',
        "om/src/acme/om/storage/purge.py": (
            "from acme.om.storage.settings import StorageSettings\n\n\n"
            "class PurgeSettings(StorageSettings):\n    database_purge_url: str | None = None\n"
        ),
    }
    write_project(tmp_path, files)
    assert [(p.rpartition("/")[2], line) for p, line, _ in found(tmp_path, "PLC-16")] == [
        ("purge.py", 3)
    ]


def test_plc16_the_names_option_guards_a_variable_of_the_projects_own(tmp_path):
    files = {AGENT: 'import os\n\nTOKEN = os.environ.get("VENDOR_TOKEN")\n'}
    write_project(tmp_path, files)
    assert found(tmp_path, "PLC-16") == []
    option = '\n[tool.distro-check.options.PLC-16]\nnames = ["VENDOR_TOKEN"]\n'
    write_project(tmp_path, files, pyproject=PYPROJECT + option)
    assert [(line, m.split(";")[0]) for _, line, m in found(tmp_path, "PLC-16")] == [
        (3, "names VENDOR_TOKEN, a secret's variable")
    ]


def test_plc16_the_names_option_adds_to_the_providers_keys(tmp_path):
    files = {AGENT: 'import os\n\nKEY = os.environ.get("OPENAI_API_KEY")\n'}
    option = '\n[tool.distro-check.options.PLC-16]\nnames = ["VENDOR_TOKEN"]\n'
    write_project(tmp_path, files, pyproject=PYPROJECT + option)
    assert [(line, m.split(";")[0]) for _, line, m in found(tmp_path, "PLC-16")] == [
        (3, "names OPENAI_API_KEY, a model provider's key")
    ]


# --- FLT-12: the dashboard's labels are bounded

METRICS = (
    "import prometheus_client as prom\nfrom collections import Counter as Tally\n"
    "from prometheus_client import Gauge, Histogram\n\n"
    'PARKS = Gauge("acme_parks", "Parks by reason", ["reason", "tenant"])\n'
    'LOOPS = prom.Counter("acme_loops", "Loops", labelnames=["host_name", "session", "plan_tier"])\n'
    'SPEND = Histogram("acme_spend", "Spend", ("org_id", "matrix_version"))\n'
    'TALLY = Tally(["tenant"])\n'
)


def test_flt12_a_metric_labelled_by_an_unbounded_value_is_a_finding(tmp_path):
    write_project(tmp_path, {"om/src/acme/om/metrics.py": METRICS})
    hits = found(tmp_path, "FLT-12")
    assert [(line, m.split(",")[0]) for _, line, m in hits] == [
        (5, "labels a metric by 'tenant'"),
        (6, "labels a metric by 'host_name'"),
        (6, "labels a metric by 'session'"),
    ]


def test_flt12_bounded_labels_pass(tmp_path):
    write_project(tmp_path)
    assert found(tmp_path, "FLT-12") == []
    assert "host_pool" in (tmp_path / OBSERVABILITY).read_text()
