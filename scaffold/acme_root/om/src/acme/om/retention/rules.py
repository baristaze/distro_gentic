"""Pure rules of retention: the tighter of two policies, the policy a
session of a project takes, its expiries, and what a sweep folds into a
snapshot.

`tighter` is the one operation. A project's narrowing is folded into its
tenant's policy with it, and the tenant's policy into a session's snapshot
with it, so a narrowing never widens and a loosening never reaches back:
each field of the result is at least as strict as the same field of
either side."""

from datetime import datetime, timedelta
from uuid import UUID

from acme.om.privacy.types.session_privacy import StorageMode
from acme.om.retention.types.policy import MAX_LIFETIME, RetentionPolicy, TenantRetention
from acme.om.retention.types.snapshot import SessionRetention


def shortest(a: timedelta | None, b: timedelta | None) -> timedelta | None:
    """The shorter lifetime; None is no end."""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def earliest(a: datetime | None, b: datetime | None) -> datetime | None:
    """The earlier time; None is never."""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def tighter(a: RetentionPolicy, b: RetentionPolicy) -> RetentionPolicy:
    """Each field at its stricter value: the shorter lifetime, memory-only
    over sealed, zero retention over none. A region, once `a` holds one,
    stands; `b` sets one only where `a` has none."""
    memory_only = StorageMode.MEMORY_ONLY in (a.storage_mode, b.storage_mode)
    return RetentionPolicy(
        content_lifetime=shortest(a.content_lifetime, b.content_lifetime),
        shape_lifetime=shortest(a.shape_lifetime, b.shape_lifetime),
        storage_mode=StorageMode.MEMORY_ONLY if memory_only else StorageMode.SEALED,
        zero_retention=a.zero_retention or b.zero_retention,
        region=a.region if a.region is not None else b.region,
    )


def region_conflicts(tenant: RetentionPolicy, narrowing: RetentionPolicy) -> bool:
    """A project that names a region other than its tenant's: neither is
    tighter, so the narrowing is refused rather than folded."""
    return (
        tenant.region is not None
        and narrowing.region is not None
        and narrowing.region != tenant.region
    )


def past_bound(policy: RetentionPolicy) -> bool:
    """A lifetime past the longest a policy is written with. The write
    refuses it, so no expiry runs past a date's last year."""
    return any(
        lifetime is not None and lifetime > MAX_LIFETIME
        for lifetime in (policy.content_lifetime, policy.shape_lifetime)
    )


def effective(tenant: TenantRetention | None, project_id: UUID | None) -> RetentionPolicy:
    """The policy a session of the project takes now: its tenant's, narrowed
    by the project's when it has one. A tenant with no policy declared takes
    the loosest."""
    if tenant is None:
        return RetentionPolicy()
    narrowing = tenant.narrowing(project_id)
    return tenant.policy if narrowing is None else tighter(tenant.policy, narrowing)


def expiries(
    policy: RetentionPolicy, taken_at: datetime, at_rest: bool, now: datetime
) -> tuple[datetime | None, datetime | None]:
    """When the content and the shape of a session expire, counted from when
    its snapshot was taken. Content that rests sealed under a policy that
    no longer lets it rest expires now."""
    content = None if policy.content_lifetime is None else taken_at + policy.content_lifetime
    if at_rest and policy.storage_mode is StorageMode.MEMORY_ONLY:
        content = earliest(content, now)
    shape = None if policy.shape_lifetime is None else taken_at + policy.shape_lifetime
    return content, shape


def folded(
    snapshot: SessionRetention, current: RetentionPolicy, version: int, now: datetime
) -> SessionRetention:
    """The snapshot once the sweep has read version `version` of its tenant's
    policy, which a session of its project takes as `current`. A tightening
    moves its policy and its expiries earlier; a loosening, or no change,
    leaves both as they are and only records the version read. An expiry
    never moves later."""
    policy = tighter(snapshot.policy, current)
    if policy == snapshot.policy:
        return snapshot.model_copy(
            update={"policy_version": version, "version": snapshot.version + 1}
        )
    content, shape = expiries(policy, snapshot.created_at, snapshot.at_rest, now)
    return SessionRetention.model_validate(
        {
            **snapshot.model_dump(),
            "policy": policy,
            "policy_version": version,
            "content_expires_at": earliest(snapshot.content_expires_at, content),
            "shape_expires_at": earliest(snapshot.shape_expires_at, shape),
            "version": snapshot.version + 1,
        }
    )


def content_due(snapshot: SessionRetention, now: datetime) -> bool:
    """Its content has expired and the sweep has not yet taken it up."""
    expires = snapshot.content_expires_at
    return expires is not None and expires <= now and snapshot.content_expired_at is None


def shape_due(snapshot: SessionRetention, now: datetime) -> bool:
    """Its shape has expired and the session is not yet marked."""
    expires = snapshot.shape_expires_at
    return expires is not None and expires <= now and snapshot.shape_expired_at is None
