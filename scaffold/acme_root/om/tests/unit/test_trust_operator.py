"""An operator reads a tenant's sessions through the operator plane, naming
the tenant: `read` reads a session's shape, and opening its content takes a
grant of its own in that tenant, which neither `read` nor `write` implies.
Each opening is on the tenant's own record."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.loops import reply, said, use
from contracts.trust import Trusted, trusted

from acme.om.base import new_id
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    RequestContext,
)
from acme.om.exceptions import NotAuthorized, NotFound, ValidationFailed
from acme.om.steps.types.content import ContentState
from acme.om.steps.types.step import Actor, StepType
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.trust.exceptions import ContentNotGranted
from acme.om.trust.impl.operator import CONTENT_OPENED, GRANTED, REVOKED

PLAN = "the plan for the third quarter is to close the Lyon office"

OPS = AppContext(type=AppType.CLI, version="ops@test")


def operator(role: OperatorRole = OperatorRole.READ) -> OperatorContext:
    """A test double of the operator stage; admission is the tenancy
    manager's, and this suite is about what an admitted operator reads."""
    return OperatorContext(
        request_id=new_id(),
        app=OPS,
        identity_id=new_id(),
        email="support@example.test",
        credential_kind=CredentialKind.OPERATOR_TOKEN,
        credential_id=new_id(),
        permissions=operator_permissions_of(role),
    )


def grant_job() -> RequestContext:
    return RequestContext(request_id=new_id(), app=OPS)


async def a_session_that_said(platform: Trusted) -> UUID:
    session_id = await platform.start()
    await platform.say(session_id, PLAN)
    platform.anthropic.add(reply(said("Looking."), use("lookup")), reply(said("Noted.")))
    await platform.loops.run(platform.owner, session_id)
    return session_id


async def test_read_sees_a_sessions_shape_and_is_refused_its_content(tmp_path: Path) -> None:
    platform = trusted(tmp_path)
    plane = platform.trust.trust_operator
    org_id = platform.owner.org_id
    session_id = await a_session_that_said(platform)
    support = operator()

    shape = await plane.get_session_shape(support, org_id, session_id, 0, 100)

    assert len(shape.items) == len(await platform.history(session_id))
    (message,) = [item for item in shape.items if item.type is StepType.MESSAGE]
    assert message.content is ContentState.SEALED and message.actor is Actor.PERSON
    assert PLAN not in shape.model_dump_json() and "Noted" not in shape.model_dump_json()
    with pytest.raises(ContentNotGranted):
        await plane.get_session_content(support, org_id, session_id, 0, 100)
    with pytest.raises(ContentNotGranted):
        await plane.get_session_content(operator(OperatorRole.WRITE), org_id, session_id, 0, 100)
    events = await platform.managers.events.get_events(platform.owner, 0, 500)
    assert not [e for e in events if e.kind == CONTENT_OPENED]


async def test_a_grant_opens_one_tenants_content_until_it_ends_and_the_tenant_sees_it(
    tmp_path: Path,
) -> None:
    platform = trusted(tmp_path)
    plane = platform.trust.trust_operator
    org_id = platform.owner.org_id
    session_id = await a_session_that_said(platform)
    support = operator()
    elsewhere = new_id()
    await plane.grant_content(grant_job(), support.identity_id, elsewhere)
    with pytest.raises(ContentNotGranted):
        await plane.get_session_content(support, org_id, session_id, 0, 100)

    grant = await plane.grant_content(grant_job(), support.identity_id, org_id)
    opened = await plane.get_session_content(support, org_id, session_id, 0, 100)

    assert PLAN in opened.model_dump_json()
    assert grant.expires_at - grant.created_at == platform.trust_options.grant_lifetime
    events = await platform.managers.events.get_events(platform.owner, 0, 500)
    (seen,) = [e for e in events if e.kind == CONTENT_OPENED]
    assert seen.target_id == session_id and seen.actor_id == support.identity_id
    assert [e.kind for e in events if e.kind in (GRANTED, REVOKED)] == [GRANTED]

    assert await plane.revoke_content(grant_job(), support.identity_id, org_id)
    with pytest.raises(ContentNotGranted):
        await plane.get_session_content(support, org_id, session_id, 0, 100)
    assert not await plane.revoke_content(grant_job(), support.identity_id, org_id)


async def test_a_grant_expires_and_is_bounded(tmp_path: Path) -> None:
    platform = trusted(tmp_path)
    plane = platform.trust.trust_operator
    org_id = platform.owner.org_id
    session_id = await a_session_that_said(platform)
    support = operator()
    await plane.grant_content(grant_job(), support.identity_id, org_id, timedelta(minutes=5))
    await plane.get_session_content(support, org_id, session_id, 0, 100)
    platform.clock.now += timedelta(minutes=5)
    with pytest.raises(ContentNotGranted):
        await plane.get_session_content(support, org_id, session_id, 0, 100)
    bound = platform.trust_options.grant_bound
    with pytest.raises(ValidationFailed):
        await plane.grant_content(grant_job(), support.identity_id, org_id, bound * 2)


async def test_the_plane_names_the_tenant_and_admits_no_stage_short_of_read(
    tmp_path: Path,
) -> None:
    platform = trusted(tmp_path)
    plane = platform.trust.trust_operator
    session_id = await a_session_that_said(platform)
    with pytest.raises(NotFound):
        await plane.get_session_shape(operator(), new_id(), session_id, 0, 100)
    enrolling = operator().model_copy(update={"permissions": frozenset()})
    with pytest.raises(NotAuthorized):
        await plane.get_session_shape(enrolling, platform.owner.org_id, session_id, 0, 100)
