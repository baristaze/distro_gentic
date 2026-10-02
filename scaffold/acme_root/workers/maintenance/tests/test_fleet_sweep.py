"""Who runs the sweep, and what it carries. Every cloud worker runs it: the
maintenance worker's pass carries the platform's duties beside the purges,
and a session runner's takes back expired leases. A program a customer runs
inside its own wall, a host or a station's daemon, never runs it: it holds
no worker, no manager, and no storage, so it cannot reach the fleet."""

import ast
import tomllib
from pathlib import Path

from worker_support import build_container

from acme.workers.maintenance.loop import WorkerLoop
from acme.workers.maintenance.main import build_loop

ROOT = Path(__file__).resolve().parents[3]
"""The scaffold's root: `workers/maintenance/tests/` is three below it."""

PACKAGE = WorkerLoop.__module__.split(".")[0]
"""The root package every distribution of the scaffold shares."""

FLEET = (f"{PACKAGE}.workers", f"{PACKAGE}.om", f"{PACKAGE}.infra")
"""What a program needs to reach the fleet: a worker's loop, the managers,
or the storage and infra beneath them."""


def sources(under: Path) -> list[Path]:
    return [
        path
        for path in sorted(under.rglob("*.py"))
        if not {".venv", "node_modules", "tests"} & set(path.relative_to(ROOT).parts)
    ]


def imported(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            found.add(node.module)
    return found


def builds_a_worker_loop(path: Path) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == WorkerLoop.__name__
        for node in ast.walk(ast.parse(path.read_text(), str(path)))
    )


def test_the_maintenance_sweep_carries_the_platforms_duties(tmp_path: Path) -> None:
    loop = build_loop(build_container(tmp_path))
    duties = set(loop._across)  # pyright: ignore[reportPrivateUsage]
    # The holds nobody settled, the sessions pending with no loop, and the
    # keys and shape past their retention, beside every purge; the expired
    # leases, loops among them, open every pass of every worker.
    assert {"holds", "stalled_sessions", "retention"} <= duties
    assert not loop._options.recovery_only  # pyright: ignore[reportPrivateUsage]


def test_a_host_or_a_daemon_never_runs_the_sweep() -> None:
    """Every program under `apps/`, a host's and a daemon's among them,
    imports nothing that reaches the fleet and depends on no distribution
    that does; and the sweep's loop is built only by a cloud worker."""
    apps = ROOT / "apps"
    programs = [path.parent for path in sorted(apps.glob("*/pyproject.toml"))]
    assert apps / "host" in programs, "the host is one of them"
    for program in programs:
        for path in sources(program):
            reached = {name for name in imported(path) if name.startswith(FLEET)}
            assert not reached, f"{path.relative_to(ROOT)} imports {sorted(reached)}"
        project = tomllib.loads((program / "pyproject.toml").read_text())["project"]
        wanted = [d for d in project.get("dependencies", []) if d.startswith(f"{PACKAGE}-")]
        assert all(d.startswith(f"{PACKAGE}-client") for d in wanted), f"{program.name}: {wanted}"
    builders = [path for path in sources(ROOT) if builds_a_worker_loop(path)]
    assert builders, "the sweep's loop is built somewhere"
    assert all(path.relative_to(ROOT).parts[0] == "workers" for path in builders), builders
