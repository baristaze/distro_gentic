"""A forge's push of a session's commits, as git makes it on the
integration's own host: the repository's branches fetched into a fresh,
empty repository, the platform's bundle fetched over them with every object
checked, and the one commit named pushed to the one ref named, forward
only: a branch moves only to a commit built on its head, so no commit on it
is lost. Nothing else in the bundle is written, and nothing of the system's
or the user's git configuration takes part.

The credential, where the repository asks one, reaches git through the
environment of the commands that ask the repository, as a basic
authorization header for the repository's URL alone: never on a command
line, in a file, or in any message."""

import asyncio
import base64
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from acme.integrations.exceptions import ProviderRefused, ProviderUnavailable

TIMEOUT_SECONDS = 300.0
"""How long one git command of a push may take, a fetch included."""
INCOMING = "refs/incoming"
"""Where the bundle's refs land in the fresh repository, apart from the
repository's own."""
BRANCHES = "refs/heads/"
HELD = "refs/remotes/origin/"
"""Where the repository's branches land in the fresh repository."""


async def push_bundle(
    repository: str, ref: str, head: str, bundle: bytes, credential: tuple[str, str] | None
) -> None:
    """Points `ref` of `repository` at `head`, carrying the commits it needs
    from `bundle`. `ProviderRefused` when the bundle does not hold `head`, a
    branch's `head` is not built on the branch's own, or the repository
    refuses the move; `ProviderUnavailable` when the repository cannot be
    reached."""
    with tempfile.TemporaryDirectory(prefix="forge-push-") as root:
        repo = Path(root) / "repo"
        env = _environment(Path(root))
        remote = {**env, **_authorized(repository, credential)}
        await _git(env, None, "init", "-q", "--bare", str(repo))
        await _git(
            remote,
            repo,
            "fetch",
            "-q",
            "--no-tags",
            repository,
            "+refs/heads/*:refs/remotes/origin/*",
        )
        if bundle:
            path = Path(root) / "incoming.bundle"
            path.write_bytes(bundle)
            await _git(
                env,
                repo,
                "-c",
                "fetch.fsckObjects=true",
                "fetch",
                "-q",
                str(path),
                f"+refs/*:{INCOMING}/*",
                refused="the bundle is not one this repository can take",
            )
        await _git(
            env, repo, "cat-file", "-e", f"{head}^{{commit}}", refused=f"no commit {head} came"
        )
        held = ""
        if ref.startswith(BRANCHES):
            listed = HELD + ref.removeprefix(BRANCHES)
            held = await _git(env, repo, "for-each-ref", "--format=%(objectname)", listed)
        if held.strip():
            tip = held.split()[0]
            await _git(
                env,
                repo,
                "merge-base",
                "--is-ancestor",
                tip,
                head,
                refused=(
                    f"{ref} only moves forward, and {head} is not built on its head {tip}: "
                    "add a commit on top of it, never an amend or a rebase (`git reset "
                    f"--soft {tip}` keeps your changes to commit there)"
                ),
            )
        await _git(
            remote,
            repo,
            "push",
            "-q",
            "--no-verify",
            repository,
            f"{head}:{ref}",
            refused=f"{repository} took no {ref} at {head}",
        )


async def _git(
    env: Mapping[str, str], repo: Path | None, *args: str, refused: str | None = None
) -> str:
    """One git command, with no replacement objects; answers what it printed.
    A failure is the `refused` message when one is given, and unavailable
    otherwise; git's own output never reaches a message."""
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
        out, _ = await asyncio.wait_for(process.communicate(), TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ProviderUnavailable(f"git {args[0]} of a push ran past its time") from None
    if process.returncode != 0:
        if refused is not None:
            raise ProviderRefused(refused)
        raise ProviderUnavailable(f"git {args[0]} of a push ended with exit {process.returncode}")
    return out.decode()


def _environment(home: Path) -> dict[str, str]:
    """An environment of the integration's own: its search path, and nothing
    of the system's or the user's git configuration, nor a prompt for a
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


def _authorized(url: str, credential: tuple[str, str] | None) -> dict[str, str]:
    """A basic authorization header for requests to `url` alone, so a
    redirect to anywhere else carries none. Nothing when there is no
    credential."""
    if credential is None:
        return {}
    pair = base64.b64encode(f"{credential[0]}:{credential[1]}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{url}.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {pair}",
    }
