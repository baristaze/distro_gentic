"""The placement group: a host is a client of the gateway, and holds none of the cloud's secrets."""

from __future__ import annotations

import ast
from collections.abc import Iterator

from acme.agentic_check.model import Violation
from acme.agentic_check.project import (
    Project,
    SourceFile,
    docstrings,
    dotted,
    is_under,
    last,
    names_in,
    string,
)
from acme.distro_check.registry import rule

HOSTS = ["apps.host"]
"""The apps that run inside a customer's wall, relative to the package: the workspace host."""
REACHES = ["client"]
"""What of the platform a host imports besides its own app, relative to the package: the client of the gateway."""
SETTINGS = "pydantic_settings.BaseSettings"
"""The class every settings class of a process derives from, directly or through another."""
SECRET_TYPES = frozenset({"SecretStr", "SecretBytes"})
DATABASE = "database"
"""The prefix of the settings that reach a database: its URLs, which carry a login's password, and its pools."""
ALIASES = ("alias", "validation_alias")
"""The `Field` arguments that name a setting's variable in place of the prefix and the field."""
PROVIDER_KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
"""The variables the model providers' own libraries read their keys from."""


def imports(project: Project, file: SourceFile, tree: ast.Module) -> Iterator[tuple[ast.stmt, str]]:
    """(statement, name) for every name an import statement of `file` binds, relative ones resolved.

    `import a.b` gives `a.b`; `from a import b` gives `a.b`, whether `b`
    is a module or a name; `from a import *` gives `a`.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name
        elif isinstance(node, ast.ImportFrom):
            base = (
                project.resolve(file, node.level, node.module) if node.level else node.module or ""
            )
            for alias in node.names:
                yield node, base if alias.name == "*" else f"{base}.{alias.name}"


@rule(
    "PLC-10",
    coverage="partial",
    options=("modules", "reaches"),
    summary="A host's modules import nothing of the platform but their own app and the client of the gateway: "
    "no OM, infra, integration, service, or worker.",
)
def a_host_reaches_the_platform_through_the_gateway(project: Project) -> Iterator[Violation]:
    """The modules of an app that runs inside a customer's wall, the
    packages option `modules` names (default `apps.host`, relative to
    the package), import nothing of the package but their own app and
    the packages option `reaches` names (default `client`, the client of
    the gateway). Every import statement counts, one inside a function
    or under `TYPE_CHECKING` included, a relative one resolved first. A
    host that imports the OM, infra, an integration, a service, or a
    worker, the worker loop that runs the sweep among them, runs the
    platform's code inside the wall instead of calling the gateway. What
    a host dials, a listener it opens, and how it is deployed are
    judged."""
    keys = {"modules", "reaches"}
    apps = [project.sub(m) for m in project.option("PLC-10", "modules", HOSTS, keys)]
    reaches = [project.sub(m) for m in project.option("PLC-10", "reaches", REACHES, keys)]
    if not apps:
        return
    through = " and ".join(reaches) or "the gateway"
    for file, tree in project.trees(*apps):
        own = max((a for a in apps if is_under(file.module, a)), key=len)
        flagged: set[int] = set()  # one finding per import statement points at it
        for node, target in imports(project, file, tree):
            if id(node) in flagged or not is_under(target, project.package):
                continue
            if is_under(target, own) or any(is_under(target, r) for r in reaches):
                continue
            flagged.add(id(node))
            yield Violation.at(
                file.rel,
                node,
                f"{file.module} imports {target}; a host is a client of the gateway and reaches the "
                f"platform through {through} alone",
            )


def config_prefix(value: ast.expr | None) -> str | None:
    """The `env_prefix` a `model_config` value sets, as `SettingsConfigDict(...)` or a dict literal; else None."""
    if isinstance(value, ast.Call):
        return next((string(k.value) for k in value.keywords if k.arg == "env_prefix"), None)
    if isinstance(value, ast.Dict):
        return next(
            (
                string(v)
                for k, v in zip(value.keys, value.values, strict=True)
                if string(k) == "env_prefix"
            ),
            None,
        )
    return None


def env_prefix(project: Project, name: str, seen: set[str]) -> str | None:
    """The prefix a settings class reads its variables under: its own `model_config`'s, else the first
    base's in order that sets one, as pydantic merges a class's config over its bases'; else None."""
    if name in seen or name not in project.classes:
        return None
    seen.add(name)
    file, cls = project.classes[name]
    for node in cls.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(isinstance(t, ast.Name) and t.id == "model_config" for t in targets):
            prefix = config_prefix(
                node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
            )
            if prefix is not None:
                return prefix
    for base in cls.bases:
        full = project.full_name(file, base)
        found = env_prefix(project, full, seen) if full else None
        if found is not None:
            return found
    return None


def aliases(value: ast.expr | None) -> list[str]:
    """The variables a field's `alias` or `validation_alias` spells, upper-cased.

    Each is a string, or `AliasChoices` of strings.
    """
    if isinstance(value, ast.Call) and last(dotted(value.func)) == "Field":
        for k in value.keywords:
            if k.arg not in ALIASES:
                continue
            if (alias := string(k.value)) is not None:
                return [alias.upper()]
            if isinstance(k.value, ast.Call) and last(dotted(k.value.func)) == "AliasChoices":
                return [s.upper() for s in (string(a) for a in k.value.args) if s is not None]
    return []


def fields(project: Project, name: str) -> Iterator[tuple[ast.AnnAssign, str, list[str], bool]]:
    """(node, field, variables, aliased) for each field a settings class declares in its own body.

    A field is read from its aliases when it has any, else from the
    class's prefix followed by its name, upper-cased.
    """
    _, cls = project.classes[name]
    prefix = env_prefix(project, name, set()) or ""
    for node in cls.body:
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
            continue
        field = node.target.id
        if field == "model_config" or "ClassVar" in names_in(node.annotation):
            continue
        spelled = aliases(node.value)
        yield node, field, spelled or [f"{prefix}{field}".upper()], bool(spelled)


def cloud_secrets(project: Project, settings: list[str], hosts: list[str]) -> dict[str, str]:
    """Each variable the cloud's settings classes read a secret or a database setting from, to `Class.field`."""
    out: dict[str, str] = {}
    for name in settings:
        file, cls = project.classes[name]
        if any(is_under(file.module, h) for h in hosts):
            continue
        for node, field, found, _ in fields(project, name):
            if SECRET_TYPES.intersection(names_in(node.annotation)) or field.startswith(DATABASE):
                for variable in found:
                    out.setdefault(variable, f"the cloud's {cls.name}.{field}")
    return out


@rule(
    "PLC-16",
    coverage="partial",
    options=("modules", "names"),
    summary="No host module names a variable the cloud reads a secret or a database setting from, "
    "or a model provider's key.",
)
def a_host_holds_no_cloud_secret(project: Project) -> Iterator[Violation]:
    """The variables the cloud reads its secrets from are read off its
    settings classes: every class that derives from
    `pydantic_settings.BaseSettings`, directly or through another, and
    is not a host's. Each field whose annotation names `SecretStr` or
    `SecretBytes`, or whose name starts with `database`, is read from
    its `alias` or `validation_alias` (a string or `AliasChoices` of
    strings), else from the class's `env_prefix`, its own or its
    bases', followed by its name. Option `names` adds variables of its
    own (default `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, the
    providers' own). In the modules the packages option `modules` names
    (default `apps.host`), a string that is one of these variables, case
    aside, is a finding, and so is a field of a host's own settings
    class whose prefix and name spell one; a docstring is prose and
    never a name. What a host caches, what the platform sends it, the
    push token, and how its local store is keyed are judged."""
    keys = {"modules", "names"}
    hosts = [project.sub(m) for m in project.option("PLC-16", "modules", HOSTS, keys)]
    extra = project.option("PLC-16", "names", PROVIDER_KEYS, keys)
    if not hosts:
        return
    settings = sorted(project.subclasses(SETTINGS))
    guarded = cloud_secrets(project, settings, hosts)
    for name in extra:
        what = "a model provider's key" if name in PROVIDER_KEYS else "a secret's variable"
        guarded.setdefault(name.upper(), what)
    why = "a host holds no database credential, model key, or integration's credential"
    for file, tree in project.trees(*hosts):
        prose = docstrings(tree)
        for node in ast.walk(tree):
            text = string(node)
            if text is not None and id(node) not in prose and text.upper() in guarded:
                yield Violation.at(file.rel, node, f"names {text}, {guarded[text.upper()]}; {why}")
        for name in settings:
            if project.classes[name][0].rel != file.rel:
                continue
            for node, field, found, aliased in fields(project, name):
                hit = None if aliased else next((v for v in found if v in guarded), None)
                if hit is not None:  # an alias is a string, which the walk above reads
                    yield Violation.at(
                        file.rel, node, f"reads {field} from {hit}, {guarded[hit]}; {why}"
                    )
