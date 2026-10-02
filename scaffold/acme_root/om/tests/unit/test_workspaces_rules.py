"""The workspaces' pure rules: the egress a session pins, what a host
refuses, the egress proxy's answer, what a prepare does with the session's
branch, and which writes are work product."""

from ipaddress import ip_address

import pytest

from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.base import new_id, utcnow
from acme.om.workspaces import rules
from acme.om.workspaces.types.egress import (
    READ_ONLY,
    EgressAllowlist,
    EgressMethod,
    EgressRequest,
    EgressRule,
)
from acme.om.workspaces.types.host import HostOffer
from acme.om.workspaces.types.source import (
    BranchPlan,
    BranchState,
    PullRequestFate,
    RepositoryBinding,
    RepositoryWrite,
    WriteKind,
)

INTERNAL = rules.networks(rules.PLATFORM_NETWORKS)
PUBLIC = ip_address("93.184.215.14")
SOURCE = EgressRule(destination="git.example.com", methods=(EgressMethod.GET, EgressMethod.POST))
MIRROR = EgressRule(destination="*.mirror.example.com", methods=READ_ONLY)


def request(
    destination: str = "git.example.com",
    address: str = str(PUBLIC),
    method: EgressMethod | None = EgressMethod.GET,
    port: int = 443,
) -> EgressRequest:
    return EgressRequest(
        destination=destination, address=ip_address(address), port=port, method=method
    )


def allowlisted(asked: EgressRequest) -> bool:
    return rules.egress_decision(EgressMode.ALLOWLIST, (SOURCE, MIRROR), asked, INTERNAL).allowed


# Check 3: an allowlist refuses a destination or a method outside it.


def test_an_allowlist_lets_through_a_destination_by_a_method_it_names() -> None:
    assert allowlisted(request())
    assert allowlisted(request(method=EgressMethod.POST))
    assert allowlisted(request("pypi.mirror.example.com"))
    assert allowlisted(request("a.b.mirror.example.com", method=EgressMethod.HEAD))


@pytest.mark.parametrize(
    ("asked", "why"),
    [
        (request("exfil.example.net"), "a destination it does not name"),
        (request("mirror.example.com"), "a wildcard's own domain"),
        (request("git.example.com.evil.net"), "a name that only starts like one"),
        (request(method=EgressMethod.DELETE), "a method its rule does not take"),
        (request("pypi.mirror.example.com", method=EgressMethod.PUT), "a write to a mirror"),
        (request(port=22), "another port"),
        (request(method=None), "a request whose method nobody can read"),
        (request(str(PUBLIC), str(PUBLIC)), "an address in place of a name"),
    ],
)
def test_an_allowlist_refuses_what_it_does_not_name(asked: EgressRequest, why: str) -> None:
    decision = rules.egress_decision(EgressMode.ALLOWLIST, (SOURCE, MIRROR), asked, INTERNAL)
    assert not decision.allowed, why


def test_no_egress_refuses_everything_and_open_egress_the_platforms_insides_alone() -> None:
    assert not rules.egress_decision(EgressMode.NONE, (), request(), INTERNAL).allowed
    assert rules.egress_decision(EgressMode.OPEN, (), request("any.example.org"), INTERNAL).allowed


# Check 3: the metadata endpoint and the platform's internal network are
# never reached, whatever the egress.


@pytest.mark.parametrize(
    ("destination", "address", "why"),
    [
        ("169.254.169.254", "169.254.169.254", "the metadata endpoint by its address"),
        ("git.example.com", "169.254.169.254", "a listed name resolved to the metadata endpoint"),
        ("git.example.com", "::ffff:169.254.169.254", "the same, carried in IPv6"),
        ("git.example.com", "fd00:ec2::254", "the metadata endpoint over IPv6"),
        ("metadata.google.internal", str(PUBLIC), "a metadata endpoint by its name"),
        ("git.example.com", "10.0.12.7", "a listed name resolved to the internal network"),
        ("git.example.com", "172.20.1.1", "another private range"),
        ("git.example.com", "fd12:3456::1", "a private IPv6 range"),
        ("git.example.com", "127.0.0.1", "the host itself"),
        ("10.0.12.7", str(PUBLIC), "an internal address as the name"),
    ],
)
@pytest.mark.parametrize("egress", [EgressMode.OPEN, EgressMode.ALLOWLIST])
def test_the_platforms_insides_are_never_reached(
    destination: str, address: str, why: str, egress: EgressMode
) -> None:
    asked = request(destination, address)
    decision = rules.egress_decision(egress, (SOURCE,), asked, INTERNAL)
    assert not decision.allowed, why


def test_a_stations_network_is_never_reached() -> None:
    stations = rules.networks(("203.0.113.0/24",))
    asked = request(address="203.0.113.9")
    assert rules.egress_decision(EgressMode.OPEN, (), asked, INTERNAL).allowed
    assert not rules.egress_decision(EgressMode.OPEN, (), asked, INTERNAL + stations).allowed


# The egress a session pins.


def allowlist(
    *, open_egress: bool = False, named: tuple[EgressRule, ...] = (SOURCE,)
) -> EgressAllowlist:
    now = utcnow()
    actor = new_id()
    return EgressAllowlist(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        project_id=new_id(),
        rules=() if open_egress else named,
        open=open_egress,
        reason="the build fetches from the internet" if open_egress else None,
    )


def test_a_project_decides_a_sessions_egress_and_a_kind_without_egress_keeps_none() -> None:
    open_kind = EgressPolicy(mode=EgressMode.OPEN)
    listed = allowlist()
    assert rules.pinned_egress(open_kind, "k", listed)[:2] == (EgressMode.ALLOWLIST, (SOURCE,))
    mode, _, source = rules.pinned_egress(open_kind, "k", allowlist(open_egress=True))
    assert mode is EgressMode.OPEN and "the build fetches from the internet" in source
    assert rules.pinned_egress(open_kind, "k", allowlist(named=()))[0] is EgressMode.NONE
    closed = EgressPolicy(mode=EgressMode.NONE)
    assert rules.pinned_egress(closed, "k", allowlist(open_egress=True))[0] is EgressMode.NONE


def test_a_session_of_no_project_keeps_its_kinds_egress_and_its_hosts_read_only() -> None:
    assert rules.pinned_egress(EgressPolicy(mode=EgressMode.OPEN), "k", None)[0] is EgressMode.OPEN
    hosts = EgressPolicy(mode=EgressMode.ALLOWLIST, hosts=("git.example.com",))
    mode, named, _ = rules.pinned_egress(hosts, "k", None)
    assert mode is EgressMode.ALLOWLIST and named[0].methods == READ_ONLY


def test_open_egress_is_a_choice_recorded_with_its_reason() -> None:
    now = utcnow()
    actor = new_id()
    with pytest.raises(ValueError, match="open egress names its reason"):
        EgressAllowlist(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=actor,
            updated_by=actor,
            project_id=new_id(),
            open=True,
        )


# What a host refuses.

CLOUD = HostOffer()
WALL = HostOffer(inside_wall=True, dedicated_user=True, blocks_internal=True)


def spec(mode: IsolationMode, egress: EgressMode = EgressMode.NONE) -> IsolationSpec:
    hosts = ("git.example.com",) if egress is EgressMode.ALLOWLIST else ()
    return IsolationSpec(mode=mode, egress=EgressPolicy(mode=egress, hosts=hosts))


@pytest.mark.parametrize(
    ("asked", "offer", "running", "why"),
    [
        (spec(IsolationMode.HOST), CLOUD, 0, "a bare directory in the cloud"),
        (spec(IsolationMode.HOST), HostOffer(inside_wall=True), 0, "a directory run as anybody"),
        (spec(IsolationMode.TWIN), WALL, 0, "a twin outside local"),
        (spec(IsolationMode.CONTAINER, EgressMode.OPEN), CLOUD, 0, "open egress unbounded"),
        (spec(IsolationMode.VM, EgressMode.ALLOWLIST), WALL, 0, "an allowlist with no proxy"),
        (
            spec(IsolationMode.HOST),
            WALL.model_copy(update={"directory_only": True}),
            1,
            "a second session on a directory-only host",
        ),
    ],
)
def test_a_host_refuses_what_it_cannot_give(
    asked: IsolationSpec, offer: HostOffer, running: int, why: str
) -> None:
    assert rules.host_refusal(asked, offer, local=False, running=running) is not None, why


def test_a_host_takes_what_it_can_give_and_its_owner_sets_its_directory_sessions() -> None:
    assert rules.host_refusal(spec(IsolationMode.CONTAINER), CLOUD, local=False, running=5) is None
    assert rules.host_refusal(spec(IsolationMode.HOST), WALL, local=False, running=0) is None
    owned = WALL.model_copy(update={"directory_only": True, "directory_sessions": 3})
    assert rules.host_refusal(spec(IsolationMode.HOST), owned, local=False, running=2) is None
    # In local, the developer's own machine, the provider alone decides.
    assert rules.host_refusal(spec(IsolationMode.HOST), CLOUD, local=True, running=9) is None


# Check 2: a vanished branch is rebuilt only when its fate is known.


@pytest.mark.parametrize(
    ("remote", "local", "seen", "fate", "plan"),
    [
        (True, False, False, None, BranchPlan.TRACK),
        (True, True, True, None, BranchPlan.TRACK),
        (False, True, False, None, BranchPlan.KEEP),
        (False, False, False, None, BranchPlan.CUT),
        (False, True, True, PullRequestFate.MERGED, BranchPlan.REBUILD),
        (False, False, True, PullRequestFate.CLOSED, BranchPlan.REBUILD),
        (False, True, True, None, BranchPlan.LOST),
        (False, False, True, None, BranchPlan.LOST),
    ],
)
def test_a_vanished_branch_is_rebuilt_only_when_its_fate_is_known(
    remote: bool, local: bool, seen: bool, fate: PullRequestFate | None, plan: BranchPlan
) -> None:
    state = BranchState(remote=remote, local=local)
    assert rules.branch_plan(state, seen=seen, fate=fate) is plan


# Check 4: a session's own branch and pull request are its work product.

BOUND = RepositoryBinding(project_id=new_id(), repository="https://git.example.com/acme/app.git")
BRANCH = rules.session_branch(new_id())


@pytest.mark.parametrize(
    "write",
    [
        RepositoryWrite(repository=BOUND.repository, kind=WriteKind.PUSH, ref=BRANCH),
        RepositoryWrite(
            repository="git@git.example.com:Acme/App",
            kind=WriteKind.PUSH,
            ref=f"refs/heads/{BRANCH}",
        ),
        RepositoryWrite(
            repository="https://bot:token@git.example.com/acme/app/",
            kind=WriteKind.PUSH,
            ref=rules.snapshot_ref(BRANCH, utcnow()),
        ),
        RepositoryWrite(repository=BOUND.repository, kind=WriteKind.PULL_REQUEST, ref=BRANCH),
    ],
)
def test_the_sessions_own_branch_and_pull_request_are_its_work_product(
    write: RepositoryWrite,
) -> None:
    assert rules.is_work_product(write, BOUND, BRANCH)


@pytest.mark.parametrize(
    ("write", "why"),
    [
        (RepositoryWrite(repository=BOUND.repository, kind=WriteKind.PUSH, ref="main"), "main"),
        (
            RepositoryWrite(repository=BOUND.repository, kind=WriteKind.PUSH, ref=f"{BRANCH}-x"),
            "a branch named like its own",
        ),
        (
            RepositoryWrite(
                repository=BOUND.repository,
                kind=WriteKind.PUSH,
                ref=rules.snapshot_ref(rules.session_branch(new_id()), utcnow()),
            ),
            "another session's snapshot",
        ),
        (
            RepositoryWrite(repository=BOUND.repository, kind=WriteKind.PULL_REQUEST, ref="feat"),
            "another pull request",
        ),
        (
            RepositoryWrite(
                repository="https://git.example.com/acme/other.git", kind=WriteKind.PUSH, ref=BRANCH
            ),
            "another repository",
        ),
        (
            RepositoryWrite(repository=BOUND.repository, kind=WriteKind.OTHER, ref=BRANCH),
            "an issue or a release",
        ),
    ],
)
def test_every_other_write_acts_outward(write: RepositoryWrite, why: str) -> None:
    assert not rules.is_work_product(write, BOUND, BRANCH), why
    own = RepositoryWrite(repository=BOUND.repository, kind=WriteKind.PUSH, ref=BRANCH)
    assert not rules.is_work_product(own, None, BRANCH), "no repository is bound"
