"""Pure rules of the matrix: which row answers a question, which fills a
session may run on, and why a version may not be published. Values in,
values out; no clock, no storage."""

from collections.abc import Callable, Collection, Iterable, Sequence

from acme.integrations.model_providers.types import ProviderName
from acme.om.matrix.types.matrix import MatrixQuery, MatrixRow, MatrixVersion
from acme.om.matrix.types.record import BenchmarkResult, ModelRef
from acme.om.models.types.fill import Eligibility, Fill, ModelRole
from acme.om.retention.types.policy import RetentionPolicy

Admits = Callable[[Fill], bool]
"""Whether a session may run on a fill."""


def answer(rows: Sequence[MatrixRow], query: MatrixQuery, admits: Admits) -> tuple[Fill, ...]:
    """The fills of the most specific row that matches `query`, those
    `admits` takes, in the row's order: the fill, then its fallbacks. What a
    session may not run on is filtered out before the row is chosen, so a
    row left with none answers nothing and a less specific one answers. An
    empty answer when no row is left."""
    best: tuple[Fill, ...] = ()
    best_key: tuple[int, tuple[bool, ...]] | None = None
    for row in rows:
        if not row.key.matches(query):
            continue
        fills = tuple(fill for fill in row.fills if admits(fill))
        if not fills:
            continue
        specificity = row.key.specificity
        if best_key is None or specificity > best_key:
            best, best_key = fills, specificity
    return best


def admitted(
    eligibility: Eligibility,
    retired: frozenset[ModelRef],
    held: frozenset[ProviderName] | None,
) -> Admits:
    """What a session may run on: a fill that meets what the session
    requires, of a model no provider retired, and, for a tenant on its own
    keys (`held`, the providers it holds a live key for), from a provider it
    holds a key for. None for `held` is a tenant the platform's key serves."""

    def admits(fill: Fill) -> bool:
        return (
            eligibility.admits(fill.eligibility)
            and ModelRef.of(fill) not in retired
            and (held is None or fill.provider in held)
        )

    return admits


def required(passed: Eligibility, policy: RetentionPolicy) -> Eligibility | None:
    """What a session requires of every fill: the tighter of what its caller
    passed and what its tenant's retention says, zero retention and a region.
    None when the two name different regions, which no fill can meet."""
    if passed.region is not None and policy.region is not None and passed.region != policy.region:
        return None
    return Eligibility(
        zero_retention=passed.zero_retention or policy.zero_retention,
        region=passed.region or policy.region,
    )


def with_choice(fills: tuple[Fill, ...], chosen: Fill | None) -> tuple[Fill, ...]:
    """The tenant's own choice first, when it has one the answer could be
    resolved to, and the row's fills after it as its fallbacks."""
    if chosen is None:
        return fills
    return (chosen, *(fill for fill in fills if fill != chosen))


def serves(version: MatrixVersion, role: ModelRole) -> frozenset[Fill]:
    """Every fill the version qualified for `role`: the fills of each row
    that serves it."""
    return frozenset(
        fill for row in version.rows if role in version.roles_of(row) for fill in row.fills
    )


def choosable(
    version: MatrixVersion, role: ModelRole, keyed: Collection[ProviderName]
) -> tuple[Fill, ...]:
    """The fills a tenant on its own keys may choose for `role`: each fill
    the version qualified for it (`serves`) from a provider in `keyed`, once,
    in the order the version's rows name them."""
    return tuple(
        dict.fromkeys(
            fill
            for row in version.rows
            if role in version.roles_of(row)
            for fill in row.fills
            if fill.provider in keyed
        )
    )


def latest_results(
    results: Iterable[BenchmarkResult],
) -> dict[tuple[ModelRef, ModelRole], BenchmarkResult]:
    """The latest recorded result for each model and model role."""
    latest: dict[tuple[ModelRef, ModelRole], BenchmarkResult] = {}
    for result in results:
        key = (result.ref, result.role)
        held = latest.get(key)
        if held is None or (result.created_at, result.id) > (held.created_at, held.id):
            latest[key] = result
    return latest


def publish_refusals(
    version: MatrixVersion,
    *,
    priced: Callable[[ModelRef], bool],
    qualified: Callable[[ModelRef, ModelRole], bool],
    retired: Callable[[ModelRef], bool],
    required: Collection[ModelRole],
) -> list[str]:
    """Why `version` may not be published, every reason, or none. It needs
    the row that matches every question, and it serves every model role in
    `required`, the roles the kinds it answers call. Each fill of each row
    needs a price row of its own, a passing benchmark for every model role
    the row serves, and a model no provider has retired."""
    refusals: list[str] = []
    if not any(row.key.everything for row in version.rows):
        refusals.append("no row matches every question")
    refusals.extend(
        f"it serves no model role {role}, which a kind it answers calls"
        for role in sorted(set(required) - set(version.roles))
    )
    for row in version.rows:
        for fill in row.fills:
            model = ModelRef.of(fill)
            if not priced(model):
                refusals.append(f"{model.name} has no price row of its own")
            if retired(model):
                refusals.append(f"{model.name} is retired")
            refusals.extend(
                f"{model.name} has no passing benchmark for the model role {role}"
                for role in version.roles_of(row)
                if not qualified(model, role)
            )
    return list(dict.fromkeys(refusals))
