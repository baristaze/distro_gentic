"""The `distro-check` command line.

Exit status: 0 when clean, 1 when there are findings, 2 on a
configuration or usage error or when a rule raised. A file that does
not parse is a `PARSE` finding, never a crash; a rule that raises is an
`ERROR` finding, and the other rules still run. The run itself is the
engine's (`acme.agentic_check.runner`), over the platform's rules.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from acme.agentic_check import report as engine_report
from acme.agentic_check.cli import pinned_python, split
from acme.agentic_check.config import ConfigError
from acme.agentic_check.runner import ERROR as RULE_ERROR
from acme.agentic_check.runner import run
from acme.distro_check import __version__, registry, report
from acme.distro_check.config import TABLE, find_root, load
from acme.distro_check.lenses import CORE, GROUPS
from acme.distro_check.project import Project

CLEAN, FINDINGS, ERROR = 0, 1, 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="distro-check",
        description="Static checks for the lenses of the distro_gentic spec.",
        allow_abbrev=False,
    )
    p.add_argument(
        "paths",
        nargs="*",
        help="report findings only under these paths (the whole project is read)",
    )
    p.add_argument(
        "--root",
        help=f"repository root (default: nearest directory whose pyproject.toml has [tool.{TABLE}])",
    )
    p.add_argument("--group", help="only the rules of these lens groups, comma-separated")
    p.add_argument("--rule", help="only these rules, comma-separated lens ids")
    p.add_argument(
        "--format", choices=("text", "json"), default="text", help="report format (default: text)"
    )
    p.add_argument("--list", action="store_true", help="print every rule and exit")
    p.add_argument("--version", action="version", version=f"distro-check {__version__}")
    return p


def error(message: str) -> int:
    print(f"distro-check: error: {message}", file=sys.stderr)
    return ERROR


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path(args.root) if args.root else find_root(Path.cwd())
    try:
        config = load(root, need_package=not args.list)
        everything = registry.rules()
    except (ConfigError, registry.RegistryError) as e:
        return error(str(e))
    known = {r.id for r in everything}

    groups = split(args.group)
    unknown_groups = [g for g in groups if g not in GROUPS]
    if unknown_groups:
        return error(
            f"unknown group(s) {', '.join(unknown_groups)}; groups are {', '.join(GROUPS)}"
        )
    ids = split(args.rule)
    unknown_ids = [i for i in ids if i not in known]
    if unknown_ids:
        return error(f"unknown rule(s) {', '.join(unknown_ids)}; `distro-check --list` prints them")
    selected = [
        r for r in everything if (not groups or r.group in groups) and (not ids or r.id in ids)
    ]

    if args.list:
        print(engine_report.listing(selected))
        return CLEAN

    for d in (*config.disabled, *config.exceptions):
        if d.rule not in known:
            return error(f"[tool.{TABLE}] names unknown rule {d.rule}")
        if d.rule in CORE:
            kind = "a disable" if d.path is None else "an exception"
            return error(
                f"[tool.{TABLE}] has {kind} for {d.rule}, whose lens states a core rule of the spec: "
                "a departure from it is a different platform, never a deviation"
            )
    declared = {r.id: set(r.options) for r in everything}
    for name, entries in config.options.items():
        if name not in known:
            return error(f"[tool.{TABLE}.options] names unknown rule {name}")
        unknown_keys = sorted(set(entries) - declared[name])
        if unknown_keys:
            return error(f"[tool.{TABLE}.options.{name}]: unknown key(s) {', '.join(unknown_keys)}")
    disabled = {d.rule for d in config.disabled}
    selected = [r for r in selected if r.id not in disabled]
    if not selected:
        return error(f"every selected rule is disabled by [tool.{TABLE}]; nothing to run")

    paths: list[str] = []
    for raw in args.paths:
        try:
            paths.append(Path(raw).resolve().relative_to(config.root).as_posix())
        except ValueError:
            return error(f"{raw} is outside the root {config.root}")

    pinned = pinned_python(config.root)
    if pinned is not None and pinned > sys.version_info[:2]:
        return error(
            f"the project pins Python {pinned[0]}.{pinned[1]} (.python-version) and distro-check runs on "
            f"{sys.version_info[0]}.{sys.version_info[1]}, whose parser cannot read it; "
            f"run it with that Python, e.g. uvx --python {pinned[0]}.{pinned[1]} ..."
        )
    project = Project(config, declared)
    if not project.python_files:
        return error(
            f"the source globs {', '.join(config.src)} match no Python file under {config.root}; "
            f"check `src` under [tool.{TABLE}]"
        )
    # A misspelt package reads as a clean project: every rule looks under a
    # package no file is in, and finds nothing. That is an error, not a pass.
    if not project.modules_under(config.package):
        found = sorted({f.module.split(".")[0] for f in project.python_files})
        return error(
            f"no module is under the package {config.package!r}; the source roots hold {', '.join(found)}"
        )
    try:
        result = run(project, selected, [p for p in paths if p != "."])
    except ConfigError as e:
        return error(str(e))
    except Exception:
        traceback.print_exc()
        return error(
            "distro-check failed outside any rule; this is a bug in distro-check, not in the project"
        )
    result.version = __version__
    print(engine_report.json(result) if args.format == "json" else report.text(result))
    failed = [f for f in result.findings if f.rule == RULE_ERROR]
    if failed:
        return error(f"{len(failed)} rule(s) raised; this is a bug in the rule, not in the project")
    return FINDINGS if result.findings else CLEAN
