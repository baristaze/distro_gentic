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
internal network. Git is held to the addresses checked, and follows no
redirect. In `local`, the developer's own machine, a
repository on disk is read too.

A private repository is read with its project's fetch credential. It
reaches git through the environment of the commands that ask the
repository, as a header for the repository's URL alone: never on a command
line, in a file, or in any message, and never in a workspace."""

import asyncio
import base64
import os
import socket
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field

from acme.om.base import Platform
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
PROTOCOLS = "http:https"
"""The protocols git reads a repository by; `file` too where one on disk is
read."""

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
"""A host's addresses at a port, as a resolver answers them."""


class ReaderOptions(Platform):
    # How long one git command of a read may take, a fetch included.
    timeout: timedelta = timedelta(minutes=2)
    # The most paths a delivery lists.
    max_paths: int = Field(default=10_000, gt=0)
    # The most bytes a bundle brought into a workspace holds.
    max_bundle: int = Field(default=512 * 2**20, gt=0)


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
        self, binding: RepositoryBinding, branch: str, credential: FetchCredential | None = None
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
            remote = {**env, **await self._reached(url, credential)}
            await self._git(env, None, "init", "-q", "--bare", str(repo))
            default = binding.default_branch or _default_of(
                await self._git(remote, repo, "ls-remote", "--symref", url, "HEAD")
            )
            wanted = [f"+refs/heads/{default}:refs/heads/{default}"]
            if (await self._git(remote, repo, "ls-remote", url, f"refs/heads/{branch}")).strip():
                wanted.append(f"+refs/heads/{branch}:refs/heads/{branch}")
            # The tags in the branches' history come along, as git follows
            # them, so the checkout describes its commits as the repository
            # does.
            await self._git(remote, repo, "fetch", "-q", url, *wanted)
            bundle = Path(root) / "incoming.bundle"
            await self._git(
                env, repo, "bundle", "create", "-q", str(bundle), "--branches", "--tags"
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


async def _resolved(host: str, port: int) -> tuple[str, ...]:
    found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(info[4][0]) for info in found))


def _is_address(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


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
