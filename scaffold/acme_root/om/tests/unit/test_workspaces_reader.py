"""The platform's read of a bound repository, on its own host, reaches only
where a workspace may: a host any of whose addresses is in a walled network
is refused before anything is fetched, git reads at the addresses checked
and nowhere else, and a redirect is not followed. A repository on disk is
read only where the root allows it, as `local` does.

The repository is served by git's plain HTTP from this host's loopback, so
the walls of these reads leave the loopback out, and the names they read
resolve through a table of the test's own."""

import shutil
import subprocess
import threading
from collections.abc import Awaitable, Callable, Iterator, Sequence
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest

from acme.om.base import new_id
from acme.om.exceptions import Unavailable
from acme.om.workspaces import rules
from acme.om.workspaces.impl.reader import RepositoryReaderGitImpl
from acme.om.workspaces.types.source import RepositoryBinding

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git is not on this host")

WALLS = rules.networks(("10.0.0.0/8", "169.254.0.0/16"))
"""A private range and the metadata endpoints', and not the loopback."""
BRANCH = "sessions/one"


def git(where: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(where), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.rstrip()


class Served(ThreadingHTTPServer):
    """The repositories under `root`, served from this host's loopback; it
    counts the requests it answered. A path under `/moved/` answers a
    redirect to the same path without it."""

    def __init__(self, root: Path) -> None:
        super().__init__(("127.0.0.1", 0), partial(Answering, directory=str(root)))
        self.requests = 0

    @property
    def port(self) -> int:
        return int(self.server_address[1])


class Answering(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        served = cast(Served, self.server)
        served.requests += 1
        if self.path.startswith("/moved/"):
            self.send_response(301)
            self.send_header("Location", self.path.removeprefix("/moved"))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        return None


@pytest.fixture
def served(tmp_path: Path) -> Iterator[Served]:
    """A repository with a default branch and a session's branch one
    commit ahead, served as plain files."""
    remote = tmp_path / "served" / "ajax" / "app.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("the project\n")
    git(seed, "add", "README.md")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "1")
    git(seed, "checkout", "-q", "-b", BRANCH)
    (seed / "total.py").write_text("TOTAL = 3\n")
    git(seed, "add", "total.py")
    git(seed, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "2")
    git(seed, "push", "-q", str(remote), "main", BRANCH)
    git(remote, "update-server-info")
    server = Served(tmp_path / "served")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def resolving(table: dict[str, Sequence[str]]) -> Callable[[str, int], Awaitable[Sequence[str]]]:
    async def resolve(host: str, port: int) -> Sequence[str]:
        return table[host]

    return resolve


def bound(url: str) -> RepositoryBinding:
    return RepositoryBinding(project_id=new_id(), repository=url)


@pytest.mark.parametrize(
    "addresses",
    [
        ("10.1.2.3",),
        ("93.184.216.34", "10.1.2.3"),
        ("::ffff:10.1.2.3",),
        ("169.254.169.254",),
        ("127.0.0.1",),
    ],
    ids=["private", "one-of-two", "carried-in-ipv6", "metadata", "the-servers-own"],
)
async def test_a_host_that_resolves_into_a_walled_network_is_refused_with_nothing_fetched(
    served: Served, addresses: tuple[str, ...]
) -> None:
    # The loopback is walled too here, so a read that went ahead would
    # reach the server.
    walls = (*WALLS, *rules.networks(("127.0.0.0/8",)))
    reader = RepositoryReaderGitImpl(walled=walls, resolve=resolving({"git.corp.test": addresses}))
    binding = bound(f"http://git.corp.test:{served.port}/ajax/app.git")

    with pytest.raises(Unavailable, match=r"git\.corp\.test is at .*, where the platform reads"):
        await reader.incoming(binding, BRANCH)
    with pytest.raises(Unavailable, match="where the platform reads nothing"):
        await reader.delivered(binding, BRANCH)

    assert served.requests == 0, "nothing was fetched"


@pytest.mark.parametrize(
    "host",
    ["%67it.example.test", "git_corp.example.test", "gït.example.test", "[fe80::1%25lo0]"],
    ids=["percent-encoded", "underscore", "non-ascii", "zoned-address"],
)
async def test_a_host_named_by_more_than_plain_letters_is_refused_with_nothing_fetched(
    served: Served, host: str
) -> None:
    # Curl decodes `%67` to `g` before it looks the name up, so the name
    # checked would not be the name reached.
    asked: list[str] = []

    async def resolve(name: str, port: int) -> Sequence[str]:
        asked.append(name)
        return ("127.0.0.1",)

    reader = RepositoryReaderGitImpl(walled=WALLS, resolve=resolve)
    binding = bound(f"http://{host}:{served.port}/ajax/app.git")

    with pytest.raises(Unavailable, match="named by more than letters, digits"):
        await reader.incoming(binding, BRANCH)
    with pytest.raises(Unavailable, match="named by more than letters, digits"):
        await reader.delivered(binding, BRANCH)

    assert asked == [], "nothing was resolved"
    assert served.requests == 0, "nothing was fetched"


async def test_the_default_walls_refuse_a_private_range(served: Served) -> None:
    reader = RepositoryReaderGitImpl(resolve=resolving({"git.corp.test": ("172.16.0.9",)}))
    with pytest.raises(Unavailable, match=r"172\.16\.0\.9"):
        await reader.incoming(bound("https://git.corp.test/ajax/app.git"), BRANCH)


async def test_a_public_host_is_read_at_the_address_checked(served: Served, tmp_path: Path) -> None:
    # The name is no one's: git reaches the server only at the address the
    # check answered.
    reader = RepositoryReaderGitImpl(
        walled=WALLS, resolve=resolving({"git.example.test": ("127.0.0.1",)})
    )
    binding = bound(f"http://git.example.test:{served.port}/ajax/app.git")

    incoming = await reader.incoming(binding, BRANCH)
    delivered = await reader.delivered(binding, BRANCH)

    bundle = tmp_path / "incoming.bundle"
    bundle.write_bytes(incoming.bundle)
    heads = git(tmp_path, "bundle", "list-heads", str(bundle))
    assert incoming.default_branch == "main"
    assert {line.split()[1] for line in heads.splitlines()} == {
        "refs/heads/main",
        f"refs/heads/{BRANCH}",
    }
    assert delivered.changed == ("total.py",)
    assert served.requests > 0


async def test_a_redirect_is_not_followed(served: Served) -> None:
    reader = RepositoryReaderGitImpl(
        walled=WALLS, resolve=resolving({"git.example.test": ("127.0.0.1",)})
    )
    binding = bound(f"http://git.example.test:{served.port}/moved/ajax/app.git")

    with pytest.raises(Unavailable):
        await reader.incoming(binding, BRANCH)

    assert served.requests == 1, "the redirect alone was answered"


@pytest.mark.parametrize(
    "url",
    ["{remote}", "file://{remote}", "ssh://git.example.test/ajax/app.git", "git.example.test:ajax"],
    ids=["path", "file", "ssh", "scp"],
)
async def test_a_repository_by_any_other_way_is_refused(
    served: Served, tmp_path: Path, url: str
) -> None:
    remote = tmp_path / "served" / "ajax" / "app.git"
    reader = RepositoryReaderGitImpl(resolve=resolving({}))
    with pytest.raises(Unavailable, match="over http or https alone"):
        await reader.incoming(bound(url.format(remote=remote)), BRANCH)


async def test_a_repository_on_disk_is_read_where_the_root_allows_it(
    served: Served, tmp_path: Path
) -> None:
    remote = tmp_path / "served" / "ajax" / "app.git"

    incoming = await RepositoryReaderGitImpl(on_disk=True).incoming(bound(str(remote)), BRANCH)

    assert incoming.default_branch == "main"
