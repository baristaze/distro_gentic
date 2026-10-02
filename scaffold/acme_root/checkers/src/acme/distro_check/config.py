"""The project's configuration: `[tool.distro-check]` in its root `pyproject.toml`.

The table has the engine's keys, defaults, and value
(`acme.agentic_check.config.Config`), so a project built on the
platform's scaffold names only its package:

    [tool.distro-check]
    package = "acme"
    # src = ["om/src", "infra/src", "integrations/src", ...]   # the engine's DEFAULT_SRC
    # exclude = ["**/migrations/**"]

    [tool.distro-check.options.PLC-10]   # a rule fed the project's own names
    modules = ["apps.host", "apps.station_daemon"]

    [[tool.distro-check.disable]]
    rule = "FLT-12"
    adr = "docs/adr/3001-the-dashboard-is-drawn-by-hand.md"
    reason = "one line"

    [[tool.distro-check.exception]]
    rule = "PLC-10"
    path = "apps/host/src/acme/apps/host/legacy.py"
    adr = "docs/adr/3002-the-legacy-host-imports-the-om.md"
    reason = "one line"

With no `[tool.distro-check]` table at all, the checker still runs:
the package is inferred as the engine infers it, and there are no
disables or exceptions.

A disable or an exception is a deviation from the platform's spec, so
each names an ADR file under `docs/adr/` that exists, and the command
line refuses one for a rule whose lens is `core` (`lenses.CORE`).
Anything else is a `ConfigError`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from acme.agentic_check.config import (
    ADR_FOLDER,
    DEFAULT_SRC,
    DISABLE_KEYS,
    EXCEPTION_KEYS,
    KEYS,
    PACKAGE,
    PYPROJECT,
    Config,
    ConfigError,
    Deviation,
    globs,
    infer_package,
    relative_glob,
    text,
)

TABLE = "distro-check"


def table(path: Path) -> dict[str, Any] | None:
    """The `[tool.distro-check]` table of a pyproject.toml, or None when it has none."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(f"{path}: {e}") from e
    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        raise ConfigError(f"{path}: [tool] is not a table")
    found = tool.get(TABLE)
    if found is not None and not isinstance(found, dict):
        raise ConfigError(f"{path}: [tool.{TABLE}] is not a table")
    return found


def find_root(start: Path) -> Path:
    """The nearest directory at or above `start` whose pyproject.toml has `[tool.distro-check]`, else `start`."""
    start = start.resolve()
    for directory in (start, *start.parents):
        candidate = directory / PYPROJECT
        if candidate.is_file():
            try:
                if table(candidate) is not None:
                    return directory
            except ConfigError:
                return directory
    return start


def deviations(root: Path, value: Any, name: str, keys: set[str]) -> tuple[Deviation, ...]:
    """The entries of `disable` or `exception`, each with an ADR file under `docs/adr/` that exists."""
    if not isinstance(value, list):
        raise ConfigError(f"[tool.{TABLE}] `{name}` is not an array of tables")
    out: list[Deviation] = []
    for i, entry in enumerate(value):
        where = f"[[tool.{TABLE}.{name}]] #{i + 1}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} is not a table with rule, adr, and reason")
        unknown = sorted(set(entry) - keys)
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")
        rule = text(entry, "rule", where)
        adr = text(entry, "adr", where)
        reason = text(entry, "reason", where)
        path = text(entry, "path", where) if "path" in keys else None
        if path is not None and not relative_glob(path):
            raise ConfigError(f"{where} ({rule}): {path!r} is not a glob relative to the root")
        target = (root / adr).resolve()
        if not target.is_relative_to((root / ADR_FOLDER).resolve()) or target.suffix != ".md":
            raise ConfigError(f"{where} ({rule}): {adr} is not a Markdown file under {ADR_FOLDER}/")
        if not target.is_file():
            raise ConfigError(f"{where} ({rule}): ADR file {adr} does not exist")
        out.append(Deviation(rule=rule, adr=adr, reason=reason, path=path))
    return tuple(out)


def rule_options(value: Any) -> dict[str, dict[str, Any]]:
    """`[tool.distro-check.options.<RULE-ID>]` tables, each keyed by a lens id.

    The CLI holds the ids and the keys to the rules.
    """
    where = f"[tool.{TABLE}.options]"
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a table of tables")
    out: dict[str, dict[str, Any]] = {}
    for rule, entries in value.items():
        if not isinstance(entries, dict):
            raise ConfigError(f"{where}.{rule} must be a table")
        out[rule] = dict(entries)
    return out


def load(root: Path, *, need_package: bool = True) -> Config:
    """Read the configuration under `root`. `need_package=False` accepts an unknown package, for `--list`."""
    root = root.resolve()
    if not root.is_dir():
        raise ConfigError(f"root {root} is not a directory")
    path = root / PYPROJECT
    data: dict[str, Any] = (table(path) or {}) if path.is_file() else {}
    unknown = sorted(set(data) - KEYS)
    if unknown:
        raise ConfigError(f"[tool.{TABLE}]: unknown key(s) {', '.join(unknown)}")
    name = data.get("package")
    if name is None:
        name = infer_package(root)
    if name is None and not need_package:
        name = ""
    if name is None:
        raise ConfigError(
            f"no package: om/src/ does not hold exactly one package; set `package` under [tool.{TABLE}]"
        )
    if not isinstance(name, str) or (name and not PACKAGE.match(name)):
        raise ConfigError(f"package {name!r} is not a dotted Python name")
    return Config(
        root=root,
        package=name,
        src=globs(data["src"], f"[tool.{TABLE}] `src`") if "src" in data else DEFAULT_SRC,
        exclude=globs(data["exclude"], f"[tool.{TABLE}] `exclude`") if "exclude" in data else (),
        disabled=deviations(root, data.get("disable", []), "disable", DISABLE_KEYS),
        exceptions=deviations(root, data.get("exception", []), "exception", EXCEPTION_KEYS),
        options=rule_options(data.get("options", {})),
    )
