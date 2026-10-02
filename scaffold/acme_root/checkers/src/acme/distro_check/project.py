"""The project under check: the engine's `Project`, whose rule options are read under `[tool.distro-check]`.

Everything a rule reads of the parsed tree, the files, the modules, the
names they bind, the classes and their bases, and the `ast` helpers,
is the engine's (`acme.agentic_check.project`). Only an option's errors
name the platform's table.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TypeVar

from acme.agentic_check import project as engine
from acme.agentic_check.config import ConfigError
from acme.distro_check.config import TABLE

T = TypeVar("T")


class Project(engine.Project):
    """The repository at `config.root`, read through `config`."""

    def option(self, rule: str, key: str, default: T, allowed: Collection[str]) -> T:
        """The project's value of `key` under `[tool.distro-check.options.<rule>]`, else `default`.

        Any key the rule does not read is a `ConfigError`, so a misspelt
        option never falls back to the default. The value has the
        default's type, and a list holds strings only.
        """
        entries = self.config.options.get(rule, {})
        unknown = sorted(set(entries) - set(allowed) - self.declared.get(rule, set()))
        if unknown:
            raise ConfigError(f"[tool.{TABLE}.options.{rule}]: unknown key(s) {', '.join(unknown)}")
        if key not in entries:
            return default
        value = entries[key]
        if not isinstance(value, type(default)) or (
            isinstance(value, list) and not all(isinstance(v, str) for v in value)
        ):
            raise ConfigError(
                f"[tool.{TABLE}.options.{rule}] `{key}` must be a {type(default).__name__}"
            )
        return value
