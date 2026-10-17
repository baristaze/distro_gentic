"""How the host's program ends, as its units read it: a status a person
must act on keeps it stopped, and any other, a crash's included, starts it
again."""

import subprocess
import sys
from pathlib import Path

from acme.apps.host.main import (
    EXIT_MISCONFIGURED,
    EXIT_NOT_ENROLLED,
    EXIT_REFUSED,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
)

ROOT = Path(__file__).resolve().parents[3]
UNITS = (
    ROOT / "deployment" / "claimant" / "claimant.service",
    ROOT / "deployment" / "vms" / "acme-host.service",
)

CRASHES = """
import sys

from acme.apps.host import main


def a_bug():
    raise RuntimeError("a bug nothing here expected")


main.settings_from_env = a_bug
sys.argv = ["acme-host", "probe"]
sys.exit(main.main())
"""
"""The host's entry point, as its console script runs it, with a command
that raises what nothing in it expects."""


def kept_stopped(unit: Path) -> set[int]:
    (line,) = (
        line
        for line in unit.read_text().splitlines()
        if line.startswith("RestartPreventExitStatus=")
    )
    return {int(status) for status in line.partition("=")[2].split()}


def test_a_host_that_crashes_exits_with_a_status_its_units_start_again() -> None:
    ended = subprocess.run(
        [sys.executable, "-c", CRASHES], capture_output=True, text=True, timeout=60, check=False
    )
    assert "a bug nothing here expected" in ended.stderr
    assert ended.returncode != 0, "a failure, which Restart=on-failure acts on"
    for unit in UNITS:
        assert ended.returncode not in kept_stopped(unit), unit.name


def test_a_status_a_person_must_act_on_keeps_the_host_stopped_and_an_outage_does_not() -> None:
    for unit in UNITS:
        stopped = kept_stopped(unit)
        assert {EXIT_USAGE, EXIT_NOT_ENROLLED, EXIT_MISCONFIGURED, EXIT_REFUSED} <= stopped
        assert EXIT_UNREACHABLE not in stopped, unit.name
