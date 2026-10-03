"""What a session delivered, read by the platform on its own host: the bound
repository's default branch and the session's branch, fetched by the
repository's URL into a fresh, empty repository in a directory of its own,
with no configuration inherited from the system or the user and no
replacement objects honoured. Nothing the agent can write takes part: not
its checkout's config, its refs, its replacements, nor its hooks. The
directory goes when the read ends.

The same read brings a workspace its checkout (`incoming`): the default
branch and the session's branch, fetched the same way and handed on as a
bundle, so the workspace fetches nothing and holds no credential.

A private repository is read with its project's fetch credential. It
reaches git through the environment of the commands that ask the
repository, as a header for the repository's URL alone: never on a command
line, in a file, or in any message, and never in a workspace."""

import asyncio
import base64
import os
import tempfile
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

from pydantic import Field

from acme.om.base import Platform
from acme.om.exceptions import Unavailable
from acme.om.workspaces.git import RepositoryReaderInterface
from acme.om.workspaces.types.credential import FetchCredential
from acme.om.workspaces.types.source import Delivered, Incoming, RepositoryBinding

BASE = "refs/delivery/base"
HEAD = "refs/delivery/head"


class ReaderOptions(Platform):
    # How long one git command of a read may take, a fetch included.
    timeout: timedelta = timedelta(minutes=2)
    # The most paths a delivery lists.
    max_paths: int = Field(default=10_000, gt=0)
    # The most bytes a bundle brought into a workspace holds.
    max_bundle: int = Field(default=512 * 2**20, gt=0)


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

    async def incoming(
        self, binding: RepositoryBinding, branch: str, credential: FetchCredential | None = None
    ) -> Incoming:
        with tempfile.TemporaryDirectory(prefix="incoming-") as root:
            repo = Path(root) / "repo"
            env = _environment(Path(root))
            url = binding.repository
            remote = {**env, **_authorized(url, credential)}
            await self._git(env, None, "init", "-q", "--bare", str(repo))
            default = binding.default_branch or _default_of(
                await self._git(remote, repo, "ls-remote", "--symref", url, "HEAD")
            )
            wanted = [f"+refs/heads/{default}:refs/heads/{default}"]
            if (await self._git(remote, repo, "ls-remote", url, f"refs/heads/{branch}")).strip():
                wanted.append(f"+refs/heads/{branch}:refs/heads/{branch}")
            await self._git(remote, repo, "fetch", "-q", "--no-tags", url, *wanted)
            bundle = Path(root) / "incoming.bundle"
            await self._git(env, repo, "bundle", "create", "-q", str(bundle), "--branches")
            if bundle.stat().st_size > self._options.max_bundle:
                raise Unavailable(
                    f"the checkout of {branch} is past the {self._options.max_bundle} bytes "
                    "a workspace is brought"
                )
            return Incoming(bundle=bundle.read_bytes(), default_branch=default)

    async def _git(self, env: Mapping[str, str], repo: Path | None, *args: str) -> str:
        """One git command, with no replacement objects, its output's first
        word kept for a sha, and all of it for a listing."""
        argv = ["git", "--no-replace-objects"]
        if repo is not None:
            argv += ["--git-dir", str(repo)]
        process = await asyncio.create_subprocess_exec(
            *argv,
            *args,
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(
                process.communicate(), self._options.timeout.total_seconds()
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise Unavailable(f"git {args[0]} of a delivery ran past its time") from None
        if process.returncode != 0:
            raise Unavailable(f"git {args[0]} of a delivery ended with exit {process.returncode}")
        text = out.decode()
        return text.split()[0] if args[0] in ("rev-parse", "merge-base") else text


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
