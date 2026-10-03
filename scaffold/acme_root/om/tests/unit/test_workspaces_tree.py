"""The tree a validation runs on, read by the platform from a repository on
this disk by its URL: the delivered commit, with every protected path taken
from the base, whatever the delivered commit holds there, and nothing of
git in it. A name that is no commit's full id, and a tree past its bound,
are refused."""

import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from acme.om.base import new_id
from acme.om.exceptions import Unavailable
from acme.om.workspaces.impl.reader import ReaderOptions, RepositoryReaderGitImpl
from acme.om.workspaces.types.source import RepositoryBinding

AUTHOR = {
    "GIT_AUTHOR_NAME": "Ann",
    "GIT_AUTHOR_EMAIL": "ann@ajax.test",
    "GIT_COMMITTER_NAME": "Ann",
    "GIT_COMMITTER_EMAIL": "ann@ajax.test",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"], "HOME": str(repo), **AUTHOR},
    )
    return done.stdout.decode().strip()


def commit(repo: Path, files: dict[str, str | None]) -> str:
    """A commit that writes each file, or removes it where it is None."""
    for name, text in files.items():
        path = repo / name
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return git(repo, "rev-parse", "HEAD")


def delivered(tmp_path: Path) -> tuple[RepositoryBinding, str, str]:
    """A repository whose base holds the checks and a fixture, and whose
    delivered head fixes the code and also edits, plants, and removes
    protected paths; served bare by a `file://` URL."""
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    base = commit(
        work,
        {"app.py": "v1", "checks/run.py": "the base's runner", "checks/fixture.txt": "fixture"},
    )
    head = commit(
        work,
        {
            "app.py": "v2",
            "checks/run.py": "a runner that always passes",
            "checks/planted.py": "planted",
            "checks/fixture.txt": None,
        },
    )
    git(tmp_path, "clone", "-q", "--bare", str(work), str(tmp_path / "served.git"))
    url = f"file://{tmp_path / 'served.git'}"
    return RepositoryBinding(project_id=new_id(), repository=url), base, head


def members(tar: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(tar)) as opened:
        return {
            member.name: (opened.extractfile(member) or io.BytesIO()).read()
            for member in opened.getmembers()
            if member.isfile()
        }


async def test_a_tree_is_the_head_with_its_protected_paths_from_the_base(tmp_path: Path) -> None:
    binding, base, head = delivered(tmp_path)

    tar = await RepositoryReaderGitImpl().tree(binding, head, base, ("checks/**",))

    assert members(tar) == {
        "app.py": b"v2",
        "checks/run.py": b"the base's runner",
        "checks/fixture.txt": b"fixture",
    }, "the head's code, and the base's checks and fixtures, nothing planted, no git"


async def test_a_tree_is_read_at_a_commit_and_within_its_bound(tmp_path: Path) -> None:
    binding, base, head = delivered(tmp_path)

    with pytest.raises(Unavailable, match="full id"):
        await RepositoryReaderGitImpl().tree(binding, "main", base, ())
    with pytest.raises(Unavailable, match="past the 100 bytes"):
        await RepositoryReaderGitImpl(ReaderOptions(max_tree=100)).tree(binding, head, base, ())
    with pytest.raises(Unavailable):
        await RepositoryReaderGitImpl().tree(binding, "f" * 40, base, ())
