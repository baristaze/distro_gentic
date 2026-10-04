"""The worker classes every tool a session can name, as the API and the
session runner do, since intake, an automation, and a message check a
session's tools here: a linked member's comment on the engineer's pull
request wakes it as their message, and a kind that names the runner's
`comment` starts."""

from pathlib import Path

from worker_support import sign_in

from acme.infra.impl.local import InfraLocalImpl
from acme.om.agents.types.kind import NO_WORKSPACE, AgentKind, DoneRule, TreeLimits
from acme.om.agents.types.request import Start
from acme.om.attribution.types.authority import AuthorityMode
from acme.om.base import EMPTY_UUID, new_id, utcnow
from acme.om.context import (
    AppContext,
    AppType,
    CredentialKind,
    RequestContext,
    Role,
    TenantContext,
    build_context,
)
from acme.om.evidence.types.provenance import Provenance
from acme.om.intake.tools import COMMENT
from acme.om.intake.types.event import Arrival, Author, AuthorKind, FeedbackEvent, WorkNames
from acme.om.intake.types.link import HandleKind
from acme.om.intake.types.route import Effect
from acme.om.platform_agents.catalog import PlatformAgents, read_corpus
from acme.om.platform_agents.kinds import ENGINEER
from acme.om.root import PlatformPorts, ProductKinds
from acme.om.storage.impl.memory import StorageMemoryImpl
from acme.om.tenancy.rules import permissions_of
from acme.workers.maintenance.container import WorkerContainer

# The repository's root, whose knowledge map the worker's image carries.
ROOT = Path(__file__).resolve().parents[3]
PR = "acme/checkout#12"
# A product's kind that acts as the platform's account.
TRIAGE = AgentKind(
    name="triage",
    version=1,
    tools=(COMMENT,),
    done_rule=DoneRule.ANSWER,
    authority=AuthorityMode.STEADY,
    tree=TreeLimits(height=1, count=0),
    isolation=NO_WORKSPACE,
)


def service(owner: TenantContext) -> TenantContext:
    """The tenant's service context, which intake routes an event under."""
    return build_context(
        RequestContext(
            request_id=new_id(), app=AppContext(type=AppType.WORKER, version="maintenance@test")
        ),
        user_id=EMPTY_UUID,
        org_id=owner.org_id,
        role=Role.SERVICE,
        permissions=permissions_of(Role.SERVICE),
        credential_kind=CredentialKind.INTERNAL,
    )


def comment(external_id: str) -> FeedbackEvent:
    return FeedbackEvent(
        id=new_id(),
        integration="forge",
        provenance=Provenance.TWIN,
        arrival=Arrival.COMMENT,
        author=Author(kind=AuthorKind.PERSON, external_id=external_id, name="ann"),
        names=WorkNames(pull_request=PR),
        text="Please rerun the payments suite.",
        occurred_at=utcnow(),
    )


async def test_a_linked_members_comment_on_the_engineers_pull_request_wakes_it(
    tmp_path: Path,
) -> None:
    container = WorkerContainer.for_tests(
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        platform_agents=PlatformAgents(corpus=read_corpus(ROOT)),
    )
    owner = await sign_in(container)
    session = await container.managers.agents.start_session(
        owner, Start(id=new_id(), kind=ENGINEER, title="the total")
    )
    await container.intake.bind_work(owner, session.id, HandleKind.PULL_REQUEST, PR)
    await container.intake.link_account(owner, "forge", "U-ANN", owner.user_id)

    routed = await container.intake.route(service(owner), comment("U-ANN"))

    assert (routed.effect, routed.session_id, routed.principal_id) == (
        Effect.WAKE,
        session.id,
        owner.user_id,
    )


async def test_a_kind_that_names_the_comment_tool_starts_in_the_worker(tmp_path: Path) -> None:
    container = WorkerContainer.for_tests(
        StorageMemoryImpl(),
        InfraLocalImpl(tmp_path),
        ports=PlatformPorts(kinds=ProductKinds(agents=(TRIAGE,))),
    )
    owner = await sign_in(container)

    session = await container.managers.agents.start_session(
        owner, Start(id=new_id(), kind=TRIAGE.name, title="the report")
    )

    assert COMMENT in session.tools
