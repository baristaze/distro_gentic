"""The demo's recorder: the parts that run without a browser.

The owner it plays as is at example.com or refused, so no frame of the
GIF shows a real address, and the copy is refused unless its seed read
the forge's twin. A request of the page off the portal's origin is
refused. The film plays a run faster, cuts a still screen short, and
pauses on each beat. The scene's search finds, with grep as the tool runs
it, every caller its report names.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent / "demo"
if str(DEMO) not in sys.path:
    sys.path.insert(0, str(DEMO))

import film  # noqa: E402
import scene  # noqa: E402
import stack  # noqa: E402


def a_copy(root: Path, env: str) -> stack.Copy:
    (root / ".env.example").write_text("# a copy\nACME_ENVIRONMENT=local\n")
    (root / ".env").write_text(env)
    return stack.Copy(root)


def test_the_owner_is_the_seeds_at_example_com(tmp_path: Path) -> None:
    copy = a_copy(tmp_path, "SEED_EMAIL=demo@example.com\nSEED_SLUG=ajax\n")
    assert stack.owner_address(copy) == "demo+acme+local+ajax@example.com"


@pytest.mark.parametrize("env", ["", "SEED_EMAIL=someone@mail.example.org\n", "SEED_EMAIL='a@example.com.evil'\n"])
def test_an_owner_elsewhere_is_refused(tmp_path: Path, env: str) -> None:
    with pytest.raises(SystemExit, match=r"example\.com"):
        stack.owner_address(a_copy(tmp_path, env))


def test_a_copy_seeded_without_the_twin_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="ACME_FORGE_INTEGRATION=twin"):
        a_copy(tmp_path, "ACME_AGENT_WORKSPACE_BACKEND=host\n").seeded_for_scene()
    a_copy(tmp_path, "ACME_FORGE_INTEGRATION=twin  # the seed's\nACME_AGENT_WORKSPACE_BACKEND=host\n").seeded_for_scene()


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("http://127.0.0.1:5183/sessions/1", True),
        ("ws://127.0.0.1:5183/v1/realtime", True),
        ("http://127.0.0.1:8110/v1/agent-sessions", False),
        ("https://fonts.googleapis.com/css2", False),
        ("http://localhost:5183/", False),
    ],
)
def test_a_request_off_the_portals_origin_is_refused(tmp_path: Path, url: str, kept: bool) -> None:
    on = stack.Stack(a_copy(tmp_path, "ACME_PORT=8110\n"), tmp_path, 5183)
    try:
        assert on.on_origin(url) is kept
    finally:
        on.repositories.rmdir()


def test_a_still_screen_is_cut_short_and_a_beat_pauses(tmp_path: Path) -> None:
    shown = film.Film(tmp_path)
    first, second, third = (tmp_path / f"{n}.png" for n in range(3))
    # A change, then ten seconds of a still screen, on which a beat settles.
    shown.frames = [(0.0, first), (0.1, second), (10.1, third)]
    shown.beats = [(0.1, "a beat")]
    timeline, marks = shown.timeline()
    seconds = dict(timeline)
    step = 1 / film.FPS
    assert seconds[second] == pytest.approx(film.IDLE + film.HOLD, abs=step)
    assert [name for _, name in marks] == ["a beat"]
    assert [path for path, _ in timeline] == [first, second, third]


def test_the_scenes_search_finds_the_callers_its_report_names(tmp_path: Path) -> None:
    for name, body in scene.REPOSITORY.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body)
    turns = scene.turns()
    searched = [
        (at, block["input"]["pattern"])
        for at, said in enumerate(turns)
        for block in said["blocks"]
        if block.get("name") == "search_code"
    ]
    assert searched
    for at, pattern in searched:
        # As the tool runs it: an extended regular expression, files named.
        found = subprocess.run(
            ["grep", "-r", "-l", "-I", "-E", "-e", pattern, "--", "."], cwd=tmp_path, capture_output=True, text=True
        )
        assert found.returncode == 0, found.stderr
        files = sorted(path.removeprefix("./") for path in found.stdout.split())
        # The definition, and every caller.
        assert files == ["src/dates.py", "src/invoice.py", "src/report.py", "tests/test_dates.py"]
        report = " ".join(block["text"] for block in turns[at + 1]["blocks"] if block["kind"] == "text")
        assert [path for path in files[1:] if path not in report] == []
