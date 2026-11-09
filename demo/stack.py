"""The stack: a copy of the scaffold, its settings, and the processes the
scene runs on.

The copy's dependencies are up, migrated, and seeded: that is the
person's, as README.md says. The rest is started here, each process in
the copy in a group of its own, and each group stopped when the
recording ends: the API and the session runner as the copy's
`portal_stack.py` starts them, on the scripted provider and the scene's
script, the maintenance worker, and the portal's dev server.
"""

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import scene

PACE = 0.05
"""Seconds between the parts of each scripted turn, so its words stream."""


class Copy:
    """A rendered copy of the scaffold: its names, and its settings as its
    `.env` holds them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        example = (root / ".env.example").read_text()
        found = re.search(r"^([A-Z][A-Z0-9_]*)_ENVIRONMENT=", example, re.M)
        if found is None:
            raise SystemExit(f"{root} is no copy of the scaffold: its .env.example names no environment")
        self.upper = found.group(1)
        self.kebab = self.upper.lower().replace("_", "-")
        if not (root / ".env").exists():
            raise SystemExit(f"{root} has no .env: README.md says what it holds")
        self.env = dotenv(root / ".env")

    def setting(self, name: str, default: str | None = None) -> str:
        value = self.env.get(name, default)
        if value is None:
            raise SystemExit(f"the copy's .env sets no {name}")
        return value

    def seeded_for_scene(self) -> None:
        """Refused unless the copy's .env names the forge's twin and host
        workspaces, which the seed reads too: the seed connects the twin
        the scene's repository is installed on."""
        for name, value in (("FORGE_INTEGRATION", "twin"), ("AGENT_WORKSPACE_BACKEND", "host")):
            if self.env.get(f"{self.upper}_{name}") != value:
                raise SystemExit(f"set {self.upper}_{name}={value} in the copy's .env, then seed it (README.md, Run)")


def dotenv(path: Path) -> dict[str, str]:
    """A dotenv file as its readers take it: one KEY=VALUE a line, blanks
    and comments skipped, an inline comment and one layer of quotes
    dropped."""
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) > 1:
            value = value[1:-1]
        else:
            value = re.sub(r"\s+#.*$", "", value)
        values[key.strip()] = value
    return values


def owner_address(copy: Copy) -> str:
    """The seeded owner's address, as `make seed` derives it from
    SEED_EMAIL; refused unless it is at example.com, so no frame shows a
    real one."""
    base = copy.setting("SEED_EMAIL", "")
    if not base.endswith("@example.com"):
        raise SystemExit(
            "the demo plays as a seeded owner at example.com: set SEED_EMAIL=demo@example.com in the copy's .env, then seed it"
        )
    local, domain = base.split("@")
    return f"{local}+{copy.kebab}+local+{copy.setting('SEED_SLUG', 'ajax')}@{domain}"


class Stack:
    """The processes the scene runs on, each started in the copy in a group
    of its own, and each group stopped when the recording ends."""

    def __init__(self, copy: Copy, folder: Path, portal_port: int) -> None:
        self.copy = copy
        self.folder = folder
        self.api_port = int(copy.setting(f"{copy.upper}_PORT", "8000"))
        self.portal = f"http://127.0.0.1:{portal_port}"
        self.portal_port = portal_port
        self.processes: list[tuple[str, subprocess.Popen[bytes]]] = []
        # The bare repositories the runner clones from. The pull request's
        # card shows their path, so it is a short one that names nobody.
        self.repositories = Path(tempfile.mkdtemp(prefix="ledger-", dir="/tmp"))

    def environment(self) -> dict[str, str]:
        """What each process runs with: the shell's basics and the scene's
        knobs, and no other variable of the shell, so no key it holds
        reaches the stack. The copy's .env gives every other setting."""
        keep = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "LC_ALL", "TERM")
        upper = self.copy.upper
        return {
            **{name: os.environ[name] for name in keep if name in os.environ},
            f"{upper}_LLM_PROVIDERS": "scripted",
            f"{upper}_LLM_SCRIPT": str(self.folder / "script.json"),
            f"{upper}_LLM_SCRIPT_PACE_SECONDS": str(PACE),
            f"{upper}_CORPUS_ROOT": ".",
            f"{upper}_FORGE_INTEGRATION": "twin",
            f"{upper}_AGENT_WORKSPACE_BACKEND": "host",
            f"{upper}_PORTAL_API_TARGET": f"http://127.0.0.1:{self.api_port}",
            "PORTAL_REPOSITORIES": str(self.repositories),
        }

    def run(self, *command: str) -> str:
        """A command in the copy, to its end; what it printed."""
        done = subprocess.run(command, cwd=self.copy.root, env=self.environment(), capture_output=True, text=True)
        if done.returncode != 0:
            raise SystemExit(f"{' '.join(command[:6])} failed:\n{done.stderr[-2000:]}")
        return done.stdout

    def prepare(self, slug: str) -> None:
        """The script, the scene's repository where the runner clones it
        from, and the policy of the agent project that binds it."""
        self.copy.seeded_for_scene()
        scene.write_script(self.folder / "script.json")
        where = self.run(
            "uv",
            "run",
            "--package",
            f"{self.copy.kebab}-api",
            "python",
            "-c",
            f"from {self.copy.upper.lower()}.services.api.seed import first_repository as f; "
            f"r = f({slug!r}); print(r.host, r.path)",
        ).split()
        host, path = where[-2], where[-1]
        scene.write_repository(self.repositories / host / f"{path}.git")
        self.run(
            "uv",
            "run",
            "--package",
            f"{self.copy.kebab}-api",
            "python",
            "services/api/tests/portal_check.py",
            "scene",
            str(self.repositories),
            slug,
        )

    def start(self) -> None:
        kebab = self.copy.kebab
        stack = "services/api/tests/portal_stack.py"
        for name, command in (
            ("api", ["uv", "run", "--package", f"{kebab}-api", "python", stack, "api", "--port", str(self.api_port)]),
            ("runner", ["uv", "run", "--package", f"{kebab}-agent-session-runner", "python", stack, "runner"]),
            ("maintenance", ["uv", "run", "--package", f"{kebab}-maintenance", f"{kebab}-maintenance", "serve"]),
            (
                "portal",
                [
                    "pnpm",
                    "--filter",
                    f"@{kebab}/portal",
                    "dev",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.portal_port),
                    "--strictPort",
                ],
            ),
        ):
            log = (self.folder / f"{name}.log").open("wb")
            process = subprocess.Popen(
                command, cwd=self.copy.root, env=self.environment(), stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            self.processes.append((name, process))
        self.ready(f"http://127.0.0.1:{self.api_port}/healthz")
        self.ready(self.portal)

    def ready(self, url: str) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            for name, process in self.processes:
                if process.poll() is not None:
                    raise SystemExit(f"the {name} process ended: {self.folder / f'{name}.log'}")
            try:
                with urllib.request.urlopen(url, timeout=2) as answer:
                    if answer.status == 200:
                        return
            except OSError:
                pass
            time.sleep(1)
        raise SystemExit(f"{url} did not answer")

    def stop(self) -> None:
        for _, process in reversed(self.processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for _, process in self.processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        shutil.rmtree(self.repositories, ignore_errors=True)
