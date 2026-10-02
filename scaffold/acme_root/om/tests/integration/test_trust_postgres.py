"""Trust over Postgres: a call's audit entry lands in the tenant's stream
with its four answers apart, and an operator's `read` sees a session's
shape at rest and never what it says, which only a grant opens."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from contracts.loops import reply, said, use
from contracts.trust import trusted

from acme.infra.impl.configured import InfraConfiguredImpl
from acme.infra.impl.settings import InfraSettings
from acme.om.attribution.types.principal import Principal, PrincipalKind
from acme.om.base import new_id
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    OperatorContext,
    OperatorRole,
    RequestContext,
    TenantContext,
)
from acme.om.root import build_managers
from acme.om.steps.types.content import ContentState
from acme.om.steps.types.header import LoopOutcome
from acme.om.steps.types.step import StepType
from acme.om.storage.impl.postgres import StoragePostgresImpl
from acme.om.storage.settings import MigrationSettings
from acme.om.tenancy.rules import operator_permissions_of
from acme.om.trust.exceptions import ContentNotGranted
from acme.om.trust.impl.manager import CALL_AUDITED
from acme.om.trust.types.identities import CallAudit

pytestmark = pytest.mark.integration

APP = AppContext(type=AppType.PORTAL, version="portal@test")
PLAN = "the plan for the third quarter is to close the Lyon office"


@pytest.fixture
async def storage(
    migration_settings: MigrationSettings, migrated: object
) -> AsyncIterator[StoragePostgresImpl]:
    root = StoragePostgresImpl(
        migration_settings.role_urls(),
        migration_settings.role_pools(),
        system_urls=migration_settings.system_role_urls(),
    )
    yield root
    await root.close()


async def an_owner(storage: StoragePostgresImpl, tmp_path: Path) -> TenantContext:
    settings = InfraSettings.model_validate(
        {"environment": "local", "buckets_root": tmp_path / "buckets"}
    )
    managers = build_managers(storage, InfraConfiguredImpl(settings))
    slug = f"ajax-{new_id().hex[-8:]}"
    owner, _ = await managers.tenancy.bootstrap(
        RequestContext(request_id=new_id(), app=APP),
        "Ajax",
        slug,
        f"ann-{slug}@example.test",
        "Ann",
    )
    return owner


async def test_a_calls_audit_entry_and_an_operators_reads_over_postgres(
    storage: StoragePostgresImpl, tmp_path: Path
) -> None:
    owner = await an_owner(storage, tmp_path)
    platform = trusted(tmp_path, storage=storage, owner=owner)
    session_id = await platform.start()
    platform.placement.walled.add(session_id)
    asker = platform.member()
    await platform.say(session_id, PLAN, asker)
    platform.anthropic.add(reply(said("Looking."), use("lookup")), reply(said("Noted.")))

    run = await platform.loops.run(owner, session_id)

    assert run.outcome is LoopOutcome.SUCCEEDED
    events = await platform.managers.events.get_events(owner, 0, 500)
    (entry,) = [e for e in events if e.kind == CALL_AUDITED]
    audit = CallAudit.model_validate(entry.payload)
    assert audit.executor == platform.placement.host
    assert audit.principal == Principal(kind=PrincipalKind.PERSON, id=owner.user_id)
    assert audit.spender == Principal(kind=PrincipalKind.PERSON, id=asker.user_id)
    assert audit.actor.agent is not None and audit.actor.agent.session_id == session_id
    assert entry.actor_id == owner.user_id, "written under the context the call ran under"

    plane = platform.trust.trust_operator
    support = OperatorContext(
        request_id=new_id(),
        app=AppContext(type=AppType.CLI, version="ops@test"),
        identity_id=new_id(),
        email="support@example.test",
        credential_kind=CredentialKind.OPERATOR_TOKEN,
        credential_id=new_id(),
        permissions=operator_permissions_of(OperatorRole.READ),
    )
    shape = await plane.get_session_shape(support, owner.org_id, session_id, 0, 100)
    (message,) = [item for item in shape.items if item.type is StepType.MESSAGE]
    assert message.content is ContentState.SEALED
    assert PLAN not in shape.model_dump_json()
    with pytest.raises(ContentNotGranted):
        await plane.get_session_content(support, owner.org_id, session_id, 0, 100)
    job = RequestContext(request_id=new_id(), app=support.app)
    await plane.grant_content(job, support.identity_id, owner.org_id)
    opened = await plane.get_session_content(support, owner.org_id, session_id, 0, 100)
    assert PLAN in opened.model_dump_json()
    assert await plane.revoke_content(job, support.identity_id, owner.org_id)
