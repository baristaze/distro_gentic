"""What a session delivered, read by the platform on its own host: the bound
repository's default branch and the session's branch, fetched by the
repository's URL into a fresh, empty repository in a directory of its own,
with no configuration inherited from the system or the user and no
replacement objects honoured. Nothing the agent can write takes part: not
its checkout's config, its refs, its replacements, nor its hooks. The
directory goes when the read ends.

The tree a validation runs on is read the same way: the delivered commit
and the protected source, each fetched alone, composed in an index of the
platform's own, and handed on as a tar with no history in it.

A private repository is read with its project's fetch credential. It
reaches git through the environment of the commands that ask the
repository, as a header for the repository's URL alone: never on a command
line, in a file, or in any message, and never in a workspace."""

import asyncio
import base64
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

from pydantic import Field

from acme.om.base import Platform
from acme.om.evidence.rules import protected_paths
from acme.om.exceptions import Unavailable
from acme.om.workspaces.git import RepositoryReaderInterface
from acme.om.workspaces.types.credential import FetchCredential
from acme.om.workspaces.types.source import Delivered, RepositoryBinding

BASE = "refs/delivery/base"
HEAD = "refs/delivery/head"
VERSION = "refs/tree/version"
SOURCE = "refs/tree/source"
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
"""A commit's full id, the one name a tree is read at."""


class ReaderOptions(Platform):
    # How long one git command of a read may take, a fetch included.
    timeout: timedelta = timedelta(minutes=2)
    # The most paths a delivery lists.
    max_paths: int = Field(default=10_000, gt=0)
    # The most bytes of a validation's tree, as a tar.
    max_tree: int = Field(default=256 * 1024 * 1024, gt=0)


class RepositoryReaderGitImpl(RepositoryReaderInterface):
    def __init__(self, options: ReaderOptions | None = None) -> None:
        self._options = options or ReaderOptions()

    async def delivered(
        self, binding: RepositoryBinding, branch: str, credential: FetchCredential | None = None
    ) -> Delivered:
        with tempfile.TemporaryDirectory(prefix="delivery-") as root:
            repo = Path(root) / "repo"
            env = _environment(Path(root))
            url = binding.repository
            remote = {**env, **_authorized(url, credential)}
            await self._git(env, None, "init", "-q", "--bare", str(repo))
            await self._git(
                remote, repo, "fetch", "-q", "--no-tags", url, f"+{binding.base_ref}:{BASE}"
            )
            held = await self._git(remote, repo, "ls-remote", url, f"refs/heads/{branch}")
            tip = await self._git(env, repo, "rev-parse", f"{BASE}^{{commit}}")
            if not held.strip():
                return Delivered(base=tip, head=tip)
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

    async def tree(
        self,
        binding: RepositoryBinding,
        version: str,
        source: str,
        protected: tuple[str, ...],
        credential: FetchCredential | None = None,
    ) -> bytes:
        for commit in (version, source):
            if not COMMIT.fullmatch(commit):
                raise Unavailable(f"a tree is read at a commit's full id, never at {commit!r}")
        with tempfile.TemporaryDirectory(prefix="tree-") as root:
            repo = Path(root) / "repo"
            env = _environment(Path(root))
            url = binding.repository
            remote = {**env, **_authorized(url, credential)}
            await self._git(env, None, "init", "-q", "--bare", str(repo))
            for commit, ref in ((version, VERSION), (source, SOURCE)):
                await self._git(
                    remote,
                    repo,
                    "fetch",
                    "-q",
                    "--depth",
                    "1",
                    "--no-tags",
                    url,
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
            tar = await self._run(
                env, repo, "archive", "--format=tar", composed, limit=self._options.max_tree
            )
        return tar

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


def _entries(listed: bytes) -> dict[str, bytes]:
    """A recursive listing's entries by their path, each kept as the listing
    wrote it, ending in its NUL, as an index reads it back."""
    entries: dict[str, bytes] = {}
    for record in listed.split(b"\0"):
        if record:
            entries[record.split(b"\t", 1)[1].decode(errors="surrogateescape")] = record + b"\0"
    return entries


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


def _authorized(url: str, credential: FetchCredential | None) -> dict[str, str]:
    """The environment that hands git the fetch credential: a basic
    authorization header for requests to `url` alone, so a redirect to
    anywhere else carries none. Nothing when there is no credential."""
    if credential is None:
        return {}
    pair = f"{credential.username}:{credential.password.get_secret_value()}"
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{url}.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {base64.b64encode(pair.encode()).decode()}",
    }
