"""What a session delivered, read by the platform on its own host: the bound
repository's default branch and the session's branch, fetched by the
repository's URL into a fresh, empty repository in a directory of its own,
with no configuration inherited from the system or the user and no
replacement objects honoured. Nothing the agent can write takes part: not
its checkout's config, its refs, its replacements, nor its hooks. The
directory goes when the read ends.

The same read brings a workspace its checkout (`incoming`): the default
branch and the session's branch, with the tags in their history, fetched
the same way and handed on as a bundle, so the workspace fetches nothing
and holds no credential.

The platform reads only where a workspace may reach. The repository is
read over http or https, at a host whose every address lies outside the
networks the platform walls off: a metadata endpoint, its own host, its
internal network. The host is named by plain ASCII letters, digits, `-` and
`.`, or by its address, so the name checked is the name git looks up. Git
is held to the addresses checked, and follows no redirect. In `local`, the developer's own machine, a
repository on disk is read too.

The tree a validation runs on is read the same way: the delivered commit
and the protected source, each fetched alone, composed in an index of the
platform's own, and handed on as a tar with no history in it. A source of
its own, a hidden suite's, is fetched the same way from its own repository,
with that repository's credential. The tar is
written from the composed tree's blobs as stored, so no `.gitattributes`
in the tree leaves a file out of it or changes a file's bytes.

A private repository is read with its project's fetch credential. It
reaches git through the environment of the commands that ask the
repository, as a header for the repository's URL alone: never on a command
line, in a file, or in any message, and never in a workspace."""

import asyncio
import base64
import io
import os
import re
import socket
import tarfile
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field

from acme.om.base import Platform
from acme.om.evidence.rules import protected_paths
from acme.om.exceptions import Unavailable
from acme.om.workspaces import rules
from acme.om.workspaces.git import RepositoryReaderInterface
from acme.om.workspaces.types.credential import FetchCredential
from acme.om.workspaces.types.source import Delivered, Incoming, RepositoryBinding

BASE = "refs/delivery/base"
HEAD = "refs/delivery/head"
WALLED: tuple[rules.Network, ...] = rules.NEVER_REACHED + rules.networks(rules.PLATFORM_NETWORKS)
"""What the platform reads no repository at unless its root says otherwise:
what no workspace reaches, and every private range."""
PLAIN_HOST = re.compile(r"[A-Za-z0-9.-]+")
"""A host's name as curl looks it up, with nothing it decodes first."""
PROTOCOLS = "http:https"
"""The protocols git reads a repository by; `file` too where one on disk is
read."""

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
"""A host's addresses at a port, as a resolver answers them."""

VERSION = "refs/tree/version"
SOURCE = "refs/tree/source"
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
"""A commit's full id, the one name a tree is read at."""
EXECUTABLE = "100755"
SYMLINK = "120000"
GITLINK = "160000"
"""A submodule's commit, which a tree holds no file of."""


class ReaderOptions(Platform):
    # How long one git command of a read may take, a fetch included.
    timeout: timedelta = timedelta(minutes=2)
    # The most paths a delivery lists.
    max_paths: int = Field(default=10_000, gt=0)
    # The most bytes a bundle brought into a workspace holds.
    max_bundle: int = Field(default=512 * 2**20, gt=0)

    # The most bytes of a validation's tree, as a tar.
    max_tree: int = Field(default=256 * 1024 * 1024, gt=0)


class RepositoryReaderGitImpl(RepositoryReaderInterface):
    """Reads at no address inside `walled`, and a repository on disk only
    `on_disk`."""

    def __init__(
        self,
        options: ReaderOptions | None = None,
        *,
        walled: Sequence[rules.Network] = WALLED,
        on_disk: bool = False,
        resolve: Resolver | None = None,
    ) -> None:
        self._options = options or ReaderOptions()
        self._walled = tuple(walled)
        self._on_disk = on_disk
        self._resolve = resolve or _resolved

    async def delivered(
        self,
        binding: RepositoryBinding,
        branch: str,
        credential: FetchCredential | None = None,
        *,
        cut: str | None = None,
    ) -> Delivered:
        with tempfile.TemporaryDirectory(prefix="delivery-") as root:
            repo = Path(root) / "repo"
            env = _environment(Path(root))
            url = binding.repository
            remote = {**env, **await self._reached(url, credential)}
            await self._git(env, None, "init", "-q", "--bare", str(repo))
            await self._git(
                remote, repo, "fetch", "-q", "--no-tags", url, f"+{binding.base_ref}:{BASE}"
            )
            held = await self._git(remote, repo, "ls-remote", url, f"refs/heads/{branch}")
            tip = await self._git(env, repo, "rev-parse", f"{BASE}^{{commit}}")
            if not held.strip():
                # Nothing delivered, from where the branch was cut: the
                # checkout's word for it, held to the default's history.
                base = tip
                if cut is not None and rules.COMMIT.fullmatch(cut):
                    if await self._holds(env, repo, cut, tip):
                        base = cut
                return Delivered(base=base, head=base)
            await self._git(
                remote, repo, "fetch", "-q", "--no-tags", url, f"+refs/heads/{branch}:{HEAD}"
            )
            head = await self._git(env, repo, "rev-parse", f"{HEAD}^{{commit}}")
            base = await self._git(env, repo, "merge-base", head, tip)
            listed = await self._git(
                env,
                repo,
                "-c",
                "core.quotePath=false",
                "diff",
                "--no-renames",
                "--name-only",
                base,
                head,
            )
        paths = [line for line in listed.splitlines() if line]
        if len(paths) > self._options.max_paths:
            raise Unavailable(f"branch {branch} changes more than {self._options.max_paths} paths")
        return Delivered(base=base, head=head, changed=tuple(sorted(set(paths))))

    async def incoming(
        self,
        binding: RepositoryBinding,
        branch: str,
        credential: FetchCredential | None = None,
        *,
        snapshot: str | None = None,
    ) -> Incoming:
        with tempfile.TemporaryDirectory(prefix="incoming-") as root:
            repo = Path(root) / "repo"
            env = _environment(Path(root))
            url = binding.repository
            remote = {**env, **await self._reached(url, credential)}
            await self._git(env, None, "init", "-q", "--bare", str(repo))
            default = binding.default_branch or _default_of(
                await self._git(remote, repo, "ls-remote", "--symref", url, "HEAD")
            )
            wanted = [f"+refs/heads/{default}:refs/heads/{default}"]
            if (await self._git(remote, repo, "ls-remote", url, f"refs/heads/{branch}")).strip():
                wanted.append(f"+refs/heads/{branch}:refs/heads/{branch}")
            kept: list[str] = []
            if snapshot is not None and snapshot.startswith(f"{rules.SNAPSHOT_PREFIX}/{branch}/"):
                if (await self._git(remote, repo, "ls-remote", url, snapshot)).strip():
                    wanted.append(f"+{snapshot}:{snapshot}")
                    kept.append(snapshot)
            # The tags in the branches' history come along, as git follows
            # them, so the checkout describes its commits as the repository
            # does.
            await self._git(remote, repo, "fetch", "-q", url, *wanted)
            bundle = Path(root) / "incoming.bundle"
            await self._git(
                env, repo, "bundle", "create", "-q", str(bundle), "--branches", "--tags", *kept
            )
            if bundle.stat().st_size > self._options.max_bundle:
                raise Unavailable(
                    f"the checkout of {branch} is past the {self._options.max_bundle} bytes "
                    "a workspace is brought"
                )
            return Incoming(bundle=bundle.read_bytes(), default_branch=default)

    async def _reached(self, url: str, credential: FetchCredential | None) -> dict[str, str]:
        """What the commands that ask the repository at `url` add to their
        environment: git held to the protocols the platform reads by and to
        the addresses checked here, following no redirect, and the fetch
        credential for `url` alone. `Unavailable`, before anything is
        fetched, when the repository is where the platform reads nothing."""
        protocols = f"{PROTOCOLS}:file" if self._on_disk else PROTOCOLS
        config = [
            ("http.followRedirects", "false"),
            *await self._pinned(url),
            *_authorized(url, credential),
        ]
        return {"GIT_ALLOW_PROTOCOL": protocols, **_configured(config)}

    async def _pinned(self, url: str) -> list[tuple[str, str]]:
        """The resolution git is held to for the host of `url`: every address
        the host resolves to, each outside the walled networks. Nothing for
        a host named by its address, which git does not resolve, nor for a
        repository on disk where one is read. The URL is in no message: it
        may carry a credential of its own."""
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            if self._on_disk and scheme in ("", "file"):
                return []
            raise Unavailable("the platform reads a repository over http or https alone")
        try:
            host, port = parts.hostname, parts.port or (443 if scheme == "https" else 80)
        except ValueError:
            host, port = None, 0
        if not host:
            raise Unavailable("the repository's URL names no host")
        if not _plain(host):
            # Curl decodes a percent-encoded name before it looks it up, so
            # a name spelled otherwise would be checked as one host and
            # reached as another.
            raise Unavailable(
                "the repository's host is named by more than letters, digits, '-' and '.'"
            )
        try:
            addresses = tuple(await self._resolve(host, port))
        except OSError:
            addresses = ()
        if not addresses:
            raise Unavailable(f"the repository's host {host} does not resolve")
        for address in addresses:
            if rules.walled(address, self._walled):
                raise Unavailable(
                    f"the repository's host {host} is at {address}, where the platform "
                    "reads nothing"
                )
        if _is_address(host):
            return []
        held = ",".join(f"[{address}]" if ":" in address else address for address in addresses)
        return [("http.curloptResolve", f"{host}:{port}:{held}")]

    async def tree(
        self,
        binding: RepositoryBinding,
        version: str,
        source: str,
        protected: tuple[str, ...],
        credential: FetchCredential | None = None,
        source_binding: RepositoryBinding | None = None,
        source_credential: FetchCredential | None = None,
    ) -> bytes:
        for commit in (version, source):
            if not COMMIT.fullmatch(commit):
                raise Unavailable(f"a tree is read at a commit's full id, never at {commit!r}")
        with tempfile.TemporaryDirectory(prefix="tree-") as root:
            repo = Path(root) / "repo"
            env = _environment(Path(root))
            url = binding.repository
            remote = {**env, **await self._reached(url, credential)}
            held, held_remote = url, remote
            if source_binding is not None:
                held = source_binding.repository
                held_remote = {**env, **await self._reached(held, source_credential)}
            await self._git(env, None, "init", "-q", "--bare", str(repo))
            for commit, ref, fetched, reached in (
                (version, VERSION, url, remote),
                (source, SOURCE, held, held_remote),
            ):
                await self._git(
                    reached,
                    repo,
                    "fetch",
                    "-q",
                    "--depth",
                    "1",
                    "--no-tags",
                    fetched,
                    f"+{commit}:{ref}",
                )
            at = _entries(await self._run(env, repo, "ls-tree", "-r", "-z", "--full-tree", VERSION))
            taken = _entries(
                await self._run(env, repo, "ls-tree", "-r", "-z", "--full-tree", SOURCE)
            )
            covered = set(protected_paths(protected, at))
            overlaid = set(protected_paths(protected, taken))
            listing = [entry for path, entry in at.items() if path not in covered]
            listing += [entry for path, entry in taken.items() if path in overlaid]
            index = {**env, "GIT_INDEX_FILE": str(Path(root) / "index")}
            await self._run(
                index, repo, "update-index", "-z", "--index-info", stdin=b"".join(listing)
            )
            composed = (await self._run(index, repo, "write-tree")).decode().strip()
            return await self._archive(env, repo, composed)

    async def _archive(self, env: Mapping[str, str], repo: Path, tree: str) -> bytes:
        """The tar of `tree`, written from its blobs as stored: no attribute
        a `.gitattributes` sets takes effect, so nothing is left out,
        substituted, or converted. Past `max_tree` bytes, `Unavailable`."""
        limit = self._options.max_tree
        listed = await self._run(env, repo, "ls-tree", "-r", "-l", "-z", "--full-tree", tree)
        entries = [_listed(record) for record in listed.split(b"\0") if record]
        if sum(size for _, _, size, _ in entries) > limit:
            raise Unavailable(f"the tree of a delivery is past the {limit} bytes it is read to")
        blobs = sorted({sha for mode, sha, _, _ in entries if mode != GITLINK})
        stored = await self._run(env, repo, "cat-file", "--batch", stdin=_lines(blobs))
        tar = _tar(entries, _blobs(stored))
        if len(tar) > limit:
            raise Unavailable(f"the tree of a delivery is past the {limit} bytes it is read to")
        return tar

    async def _holds(self, env: Mapping[str, str], repo: Path, commit: str, tip: str) -> bool:
        """Whether `tip`'s history, as fetched, holds `commit`."""
        try:
            await self._run(env, repo, "merge-base", "--is-ancestor", commit, tip)
        except Unavailable:
            return False
        return True

    async def _git(self, env: Mapping[str, str], repo: Path | None, *args: str) -> str:
        """One git command, with no replacement objects, its output's first
        word kept for a sha, and all of it for a listing."""
        text = (await self._run(env, repo, *args)).decode()
        return text.split()[0] if args[0] in ("rev-parse", "merge-base") else text

    async def _run(
        self,
        env: Mapping[str, str],
        repo: Path | None,
        *args: str,
        stdin: bytes | None = None,
        limit: int | None = None,
    ) -> bytes:
        """One git command, with no replacement objects, and its output; past
        `limit` bytes of it, `Unavailable`, with the command stopped."""
        argv = ["git", "--no-replace-objects"]
        if repo is not None:
            argv += ["--git-dir", str(repo)]
        process = await asyncio.create_subprocess_exec(
            *argv,
            *args,
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out = await asyncio.wait_for(
                _output(process, stdin, limit), self._options.timeout.total_seconds()
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise Unavailable(f"git {args[0]} of a delivery ran past its time") from None
        if out is None:
            process.kill()
            await process.wait()
            raise Unavailable(f"the tree of a delivery is past the {limit} bytes it is read to")
        if process.returncode != 0:
            raise Unavailable(f"git {args[0]} of a delivery ended with exit {process.returncode}")
        return out


async def _output(
    process: asyncio.subprocess.Process, stdin: bytes | None, limit: int | None
) -> bytes | None:
    """What the command wrote once it ended, or None the moment it wrote past
    `limit`."""
    if limit is None:
        out, _ = await process.communicate(stdin)
        return out
    assert process.stdout is not None
    read = bytearray()
    while chunk := await process.stdout.read(1 << 16):
        read += chunk
        if len(read) > limit:
            return None
    await process.wait()
    return bytes(read)


def _listed(record: bytes) -> tuple[str, str, int, str]:
    """One entry of a long recursive listing: its mode, its object, its
    size (none for a submodule's commit), and its path."""
    meta, path = record.split(b"\t", 1)
    mode, _, sha, size = meta.decode().split()
    return mode, sha, 0 if size == "-" else int(size), path.decode(errors="surrogateescape")


def _lines(shas: list[str]) -> bytes:
    return "".join(f"{sha}\n" for sha in shas).encode()


def _blobs(stored: bytes) -> dict[str, bytes]:
    """The contents of each object a batch read wrote, by its id."""
    blobs: dict[str, bytes] = {}
    at = 0
    while at < len(stored):
        end = stored.index(b"\n", at)
        sha, _, size = stored[at:end].decode().split()
        start = end + 1
        blobs[sha] = stored[start : start + int(size)]
        at = start + int(size) + 1
    return blobs


def _tar(entries: list[tuple[str, str, int, str]], blobs: Mapping[str, bytes]) -> bytes:
    """A tar of the entries, each directory before what it holds, as git
    writes one: a file with its executable bit, a link as a link, and a
    submodule as an empty directory."""
    now = int(time.time())
    out = io.BytesIO()
    made: set[str] = set()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for mode, sha, _, path in entries:
            parts = path.split("/")
            for depth in range(1, len(parts)):
                folder = "/".join(parts[:depth])
                if folder not in made:
                    made.add(folder)
                    tar.addfile(_member(folder, tarfile.DIRTYPE, 0o755, now))
            if mode == GITLINK:
                made.add(path)
                tar.addfile(_member(path, tarfile.DIRTYPE, 0o755, now))
            elif mode == SYMLINK:
                link = _member(path, tarfile.SYMTYPE, 0o777, now)
                link.linkname = blobs[sha].decode(errors="surrogateescape")
                tar.addfile(link)
            else:
                member = _member(path, tarfile.REGTYPE, 0o755 if mode == EXECUTABLE else 0o644, now)
                member.size = len(blobs[sha])
                tar.addfile(member, io.BytesIO(blobs[sha]))
    return out.getvalue()


def _member(path: str, kind: bytes, mode: int, mtime: int) -> tarfile.TarInfo:
    member = tarfile.TarInfo(path)
    member.type, member.mode, member.mtime = kind, mode, mtime
    member.uname = member.gname = "root"
    return member


def _entries(listed: bytes) -> dict[str, bytes]:
    """A recursive listing's entries by their path, each kept as the listing
    wrote it, ending in its NUL, as an index reads it back."""
    entries: dict[str, bytes] = {}
    for record in listed.split(b"\0"):
        if record:
            entries[record.split(b"\t", 1)[1].decode(errors="surrogateescape")] = record + b"\0"
    return entries


async def _resolved(host: str, port: int) -> tuple[str, ...]:
    found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(info[4][0]) for info in found))


def _is_address(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def _plain(host: str) -> bool:
    """A name of plain ASCII letters, digits, `-` and `.`, or an address with
    no zone."""
    return PLAIN_HOST.fullmatch(host) is not None or ("%" not in host and _is_address(host))


def _default_of(listed: str) -> str:
    """The branch the repository's HEAD names, as `ls-remote --symref`
    prints it: `ref: refs/heads/<name>` and a tab before `HEAD`."""
    for line in listed.splitlines():
        target, _, name = line.partition("\t")
        if name == "HEAD" and target.startswith("ref: refs/heads/"):
            return target.removeprefix("ref: refs/heads/")
    raise Unavailable("the repository names no default branch")


def _environment(home: Path) -> dict[str, str]:
    """An environment of the platform's own: its search path, and nothing of
    the system's or the user's git configuration, nor a prompt for a
    password."""
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _authorized(url: str, credential: FetchCredential | None) -> list[tuple[str, str]]:
    """The configuration that hands git the fetch credential: a basic
    authorization header for requests to `url` alone, so a redirect to
    anywhere else carries none. Nothing when there is no credential."""
    if credential is None:
        return []
    pair = f"{credential.username}:{credential.password.get_secret_value()}"
    header = f"Authorization: Basic {base64.b64encode(pair.encode()).decode()}"
    return [(f"http.{url}.extraHeader", header)]


def _configured(config: Sequence[tuple[str, str]]) -> dict[str, str]:
    """`config` as git reads it from its environment, never from its command
    line or a file."""
    env = {"GIT_CONFIG_COUNT": str(len(config))}
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env
