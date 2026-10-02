"""distro-check's framework: the registry, the configuration, exceptions, reports, and exit codes.

The run itself is the engine's checker's, which its own tests hold;
these hold what is the platform's: its catalog, its table, its core
set, and its command line. The base tree is clean under every rule, so
a finding here is one a test planted: PLC-10's, a host that imports the
OM, or FLT-12's, a metric labelled by tenant.
"""

import pytest

pytest.importorskip("tomllib")

from distro_check_fixtures import ADR, HOST, PYPROJECT, check, check_json, write, write_project

from acme.distro_check import __version__, registry
from acme.distro_check.lenses import CORE, GROUPS, LENSES

RULES = [r.id for r in registry.rules()]
BAD = {f"{HOST}/legacy.py": "from acme.om.work import requeue_stale\n"}
LABELLED = {
    "om/src/acme/om/parks.py": 'from prometheus_client import Gauge\n\nP = Gauge("p", "p", ["tenant"])\n'
}


def test_every_rule_decides_a_lens_of_its_group_at_its_severity():
    for r in registry.rules():
        assert r.severity == LENSES[r.id]
        assert GROUPS[r.group] == r.id[:3]
    with pytest.raises(registry.RegistryError, match="no lens has this id"):
        registry.make("PLC-99", lambda p: [], coverage="full", summary="x")
    with pytest.raises(registry.RegistryError, match="no lens group has the prefix"):
        registry.make("STP-01", lambda p: [], coverage="full", summary="x")
    assert "PLC-16" in CORE


def test_a_clean_tree_exits_0(tmp_path):
    write_project(tmp_path)
    code, out, err = check(tmp_path)
    assert (code, err) == (0, "")
    assert out.startswith(f"distro-check ok: {len(RULES)} rule(s) over ")


def test_a_finding_exits_1_with_a_text_line(tmp_path):
    write_project(tmp_path, BAD)
    code, out, _ = check(tmp_path)
    assert code == 1
    assert out.splitlines()[0].startswith(
        f"{HOST}/legacy.py:1:1: PLC-10 acme.apps.host.legacy imports acme.om.work"
    )
    assert f"1 finding(s) from {len(RULES)} rule(s)" in out


def test_the_json_report_carries_the_platforms_version(tmp_path):
    write_project(tmp_path, BAD)
    code, report = check_json(tmp_path)
    assert code == 1
    assert report["version"] == __version__
    assert [r["id"] for r in report["rules_run"]] == RULES
    assert (report["findings"][0]["rule"], report["findings"][0]["group"]) == (
        "PLC-10",
        "placement",
    )


def test_list_group_and_rule(tmp_path):
    write_project(tmp_path, BAD)
    code, out, _ = check(tmp_path, "--list")
    assert code == 0
    assert [line.split()[0] for line in out.splitlines()] == RULES
    assert check(tmp_path, "--group", "fleet")[0] == 0
    assert check(tmp_path, "--rule", "PLC-10")[0] == 1
    assert check(tmp_path, "--group", "steps")[0] == 2
    assert check(tmp_path, "--rule", "PLC-01")[0] == 2


def test_an_exception_with_its_adr_accepts_a_finding(tmp_path):
    entry = (
        f'\n[[tool.distro-check.exception]]\nrule = "PLC-10"\npath = "{HOST}/legacy.py"\n'
        f'adr = "{ADR}"\nreason = "an old host"\n'
    )
    write_project(tmp_path, BAD, pyproject=PYPROJECT + entry)
    code, report = check_json(tmp_path)
    assert (code, report["findings"]) == (0, [])
    assert [(a["rule"], a["path"], a["adr"]) for a in report["exceptions_applied"]] == [
        ("PLC-10", f"{HOST}/legacy.py", ADR)
    ]


def test_an_exception_that_matches_nothing_is_a_finding(tmp_path):
    entry = (
        f'\n[[tool.distro-check.exception]]\nrule = "PLC-10"\npath = "{HOST}/gone.py"\n'
        f'adr = "{ADR}"\nreason = "gone"\n'
    )
    write_project(tmp_path, pyproject=PYPROJECT + entry)
    code, report = check_json(tmp_path)
    assert code == 1
    assert [(f["rule"], f["group"]) for f in report["findings"]] == [("IGNORE", "framework")]


def test_a_disable_turns_a_rule_off_and_needs_its_adr(tmp_path):
    entry = f'\n[[tool.distro-check.disable]]\nrule = "FLT-12"\nadr = "{ADR}"\nreason = "drawn by hand"\n'
    write_project(tmp_path, LABELLED, pyproject=PYPROJECT + entry)
    code, report = check_json(tmp_path)
    assert code == 0
    assert "FLT-12" not in [r["id"] for r in report["rules_run"]]
    write_project(
        tmp_path, LABELLED, pyproject=PYPROJECT + entry.replace(ADR, "docs/adr/3999-missing.md")
    )
    code, _, err = check(tmp_path)
    assert code == 2
    assert (
        "[[tool.distro-check.disable]] #1 (FLT-12): ADR file docs/adr/3999-missing.md does not exist"
        in err
    )


@pytest.mark.parametrize("kind", ["disable", "exception"])
def test_a_rule_whose_lens_is_core_takes_no_deviation(tmp_path, kind):
    path = f'path = "{HOST}/*.py"\n' if kind == "exception" else ""
    entry = (
        f'\n[[tool.distro-check.{kind}]]\nrule = "PLC-16"\n{path}adr = "{ADR}"\nreason = "a key"\n'
    )
    write_project(tmp_path, pyproject=PYPROJECT + entry)
    code, _, err = check(tmp_path)
    assert code == 2
    article = "an" if kind == "exception" else "a"
    assert f"has {article} {kind} for PLC-16, whose lens states a core rule of the spec" in err


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("\nlocal = []\n", "[tool.distro-check]: unknown key(s) local"),
        (
            '\n[tool.distro-check.options.PLC-10]\nmodule = ["x"]\n',
            "[tool.distro-check.options.PLC-10]: unknown key(s) module",
        ),
        ('\n[tool.distro-check.options.PLC-01]\nmodules = ["x"]\n', "names unknown rule PLC-01"),
        (
            '\n[tool.distro-check.options.PLC-10]\nmodules = "x"\n',
            "[tool.distro-check.options.PLC-10] `modules` must be a list",
        ),
    ],
)
def test_a_configuration_error_exits_2(tmp_path, extra, message):
    write_project(tmp_path, pyproject=PYPROJECT + extra)
    code, _, err = check(tmp_path)
    assert code == 2
    assert message in err


def test_a_misspelt_package_exits_2(tmp_path):
    write_project(tmp_path, pyproject='[tool.distro-check]\npackage = "acne"\n')
    code, _, err = check(tmp_path)
    assert code == 2
    assert "no module is under the package 'acne'" in err


def test_the_package_is_inferred_without_a_table(tmp_path):
    write_project(tmp_path, pyproject=None)
    write(tmp_path, "pyproject.toml", "[project]\nname = 'acme'\n")
    assert check(tmp_path)[0] == 0
