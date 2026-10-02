"""The owner's ceilings: read from a file on the host, held frozen, and
applied to every item before it runs. An item that says too little is read
as the widest ask, and nothing an item carries changes a ceiling."""

import dataclasses
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from acme.apps.host.ceilings import Ceilings, ask_of, load, refusals
from acme.apps.host.config import BadSetting
from acme.client.types import ClaimedWorkView, IsolationMode

PROJECT = uuid4()
PROBED = frozenset({IsolationMode.container, IsolationMode.directory})
CEILINGS = Ceilings(
    projects=frozenset({PROJECT}),
    min_isolation=IsolationMode.container,
    egress=frozenset({"github.com:443"}),
    readable=("/srv/work",),
    people_commands=False,
)
FITS: dict[str, Any] = {
    "host_id": str(uuid4()),
    "project_id": str(PROJECT),
    "isolation": "container",
    "egress": ["github.com:443"],
    "reads": ["/srv/work/repo/README.md"],
    "by_person": False,
}


def item(payload: dict[str, Any], kind: str = "EXEC") -> ClaimedWorkView:
    return ClaimedWorkView(
        id=uuid4(),
        kind=kind,
        target_id=uuid4(),
        payload=payload,
        lease_expires_at=None,
        attempts=1,
        wire_version=1,
    )


def refused(payload: dict[str, Any], ceilings: Ceilings = CEILINGS) -> list[str]:
    return refusals(ceilings, PROBED, ask_of(item(payload)))


def test_the_owners_file_is_read_and_a_missing_one_starts_nothing(tmp_path: Path) -> None:
    path = tmp_path / "ceilings.toml"
    with pytest.raises(BadSetting):
        load(path)
    path.write_text(
        f'projects = ["{PROJECT}"]\nmin_isolation = "vm"\negress = "open"\n'
        'readable = ["/srv/work/"]\npeople_commands = true\n'
    )
    assert load(path) == Ceilings(
        projects=frozenset({PROJECT}),
        min_isolation=IsolationMode.vm,
        egress=None,
        readable=("/srv/work",),
        people_commands=True,
    )
    path.write_text('projects = "all"\n')
    assert load(path) == Ceilings(projects=None)
    for wrong in ('readable = ["srv"]\n', 'min_isolation = "none"\n', "lanes = []\n"):
        path.write_text(wrong)
        with pytest.raises(BadSetting):
            load(path)


def test_an_item_within_every_ceiling_runs() -> None:
    assert refused(FITS) == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"project_id": str(uuid4())}, "a project this host does not serve"),
        ({"isolation": "directory"}, "isolation directory below this host's minimum"),
        ({"isolation": "vm"}, "isolation vm this host did not probe"),
        ({"egress": ["github.com:443", "example.test:443"]}, "egress beyond this host's allowlist"),
        ({"reads": ["/srv/work/../../etc/shadow"]}, "a read outside this host's readable paths"),
        ({"reads": ["/srv/workshop/notes"]}, "a read outside this host's readable paths"),
        ({"by_person": True}, "a person's command, which this host does not accept"),
    ],
)
def test_each_ceiling_refuses_what_passes_it(change: dict[str, Any], reason: str) -> None:
    assert refused({**FITS, **change}) == [reason]


def test_an_item_that_says_too_little_is_read_as_the_widest_ask() -> None:
    assert refused({"host_id": str(uuid4())}) == [
        "a project this host does not serve",
        "no isolation named",
        "egress beyond this host's allowlist",
        "a read outside this host's readable paths",
        "a person's command, which this host does not accept",
    ]


def test_an_item_silent_on_its_reads_is_read_as_reading_everything() -> None:
    silent = {key: value for key, value in FITS.items() if key != "reads"}
    assert refused(silent) == ["a read outside this host's readable paths"]
    assert refused({**FITS, "reads": []}) == []


def test_letting_go_of_a_workspace_runs_nothing_and_is_never_refused() -> None:
    for operation in ("release", "purge"):
        ask = ask_of(item({"operation": operation, "host_id": str(uuid4())}, "WORKSPACE"))
        assert refusals(CEILINGS, PROBED, ask) == []
    prepare = ask_of(item({"operation": "prepare", "pool_id": str(uuid4())}, "WORKSPACE"))
    assert refusals(CEILINGS, PROBED, prepare) != []


def test_nothing_an_item_carries_widens_a_ceiling() -> None:
    widening = {
        **FITS,
        "by_person": True,
        "ceilings": {"projects": "all", "people_commands": True},
        "min_isolation": "directory",
        "people_commands": True,
        "readable": ["/"],
    }
    assert refused(widening) == ["a person's command, which this host does not accept"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        CEILINGS.people_commands = True  # type: ignore[misc]
    assert CEILINGS.people_commands is False
