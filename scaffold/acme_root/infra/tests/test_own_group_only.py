"""The claimant's own-group check, own-group-only.sh, with the groups a kind's
drop-in grants.

The groups a process holds are the system's to give, so stand-ins for `id`
and `getent` say which the claimant's user holds and what each group is
called. `make host-check` runs the same script under a real unit.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "deployment" / "claimant" / "own-group-only.sh"

# The claimant's user, the gid of its own group, and the groups on the machine.
USER = "acme-scanner"
OWN = 990
GROUP_FILE = {"acme-scanner": OWN, "users": 100, "acme-scanner-work": 991, "docker": 999}


def _stand_ins(folder: Path, held: list[int]) -> None:
    folder.mkdir()
    gids = " ".join(str(gid) for gid in [OWN, *held])
    lines = "".join(f"{name}:x:{gid}:\n" for name, gid in GROUP_FILE.items())
    scripts = {
        "id": f"""#!/bin/sh
case "$1" in
  -g) echo {OWN} ;;
  -G) echo "{gids}" ;;
  -un) echo {USER} ;;
  *) exit 1 ;;
esac
""",
        # getent group <name or gid>: its line, or nothing and 2.
        "getent": f"""#!/bin/sh
[ "$1" = group ] || exit 1
printf '%s' '{lines}' | awk -F: -v key="$2" '$1 == key || $3 == key {{ print; found = 1 }}
  END {{ exit found ? 0 : 2 }}'
""",
    }
    for name, body in scripts.items():
        path = folder / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _start(tmp_path: Path, held: list[int], *granted: str) -> subprocess.CompletedProcess[str]:
    """Starts a stand-in claimant through the check, as the unit's ExecStart does."""
    stand_ins = tmp_path / "bin"
    _stand_ins(stand_ins, held)
    flags = [flag for group in granted for flag in ("--granted", group)]
    return subprocess.run(
        ["sh", str(CHECK), *flags, "sh", "-c", "echo started"],
        capture_output=True,
        text=True,
        env={"PATH": f"{stand_ins}{os.pathsep}{os.environ['PATH']}"},
    )


@pytest.mark.parametrize(
    ("held", "granted"),
    [
        ([], []),
        ([100, 991], ["users", "acme-scanner-work"]),
        ([100], ["users", "acme-scanner-work"]),
        ([100, 991], ["100", "acme-scanner-work"]),
    ],
    ids=["its-own-granted-none", "its-own-and-its-granted", "fewer-than-granted", "granted-by-gid"],
)
def test_a_claimant_in_its_own_and_its_granted_groups_starts(
    tmp_path: Path, held: list[int], granted: list[str]
) -> None:
    result = _start(tmp_path, held, *granted)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "started\n"


@pytest.mark.parametrize(
    ("held", "granted", "refused"),
    [
        ([999], [], "docker"),
        ([100], [], "users"),
        ([100, 991, 999], ["users", "acme-scanner-work"], "docker"),
        ([100, 991], ["users"], "acme-scanner-work"),
        ([100, 4242], ["users", "nosuch"], "4242"),
    ],
    ids=[
        "granted-none-in-another",
        "granted-none-in-users",
        "in-one-beyond-its-granted",
        "in-one-of-two-granted-one",
        "in-a-nameless-gid-a-name-that-names-no-group",
    ],
)
def test_a_claimant_in_a_group_nobody_granted_is_refused(
    tmp_path: Path, held: list[int], granted: list[str], refused: str
) -> None:
    result = _start(tmp_path, held, *granted)
    assert result.returncode == 6
    assert result.stdout == ""
    assert result.stderr.startswith(f"refused: {USER} is in the group {refused},")


@pytest.mark.parametrize(
    "arguments",
    [[], ["--granted"], ["--granted", "", "true"], ["--granted", "users"]],
    ids=["no-command", "granted-without-a-group", "an-empty-group", "granted-without-a-command"],
)
def test_a_malformed_start_is_refused_as_a_setting(tmp_path: Path, arguments: list[str]) -> None:
    stand_ins = tmp_path / "bin"
    _stand_ins(stand_ins, [])
    result = subprocess.run(
        ["sh", str(CHECK), *arguments],
        capture_output=True,
        text=True,
        env={"PATH": f"{stand_ins}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 2
