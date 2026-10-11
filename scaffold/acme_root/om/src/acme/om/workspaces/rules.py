"""Pure rules of the workspaces namespace: the egress a session pins, what a
host refuses, the answer a request gets at the egress proxy, what a prepare
does with the session's branch, which writes are the session's own work
product, and what a push token reaches. Values in, values out; no clock, no
storage, no settings."""

import hmac
import html
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from uuid import UUID

from acme.infra.workspaces import EgressMode, EgressPolicy, IsolationMode, IsolationSpec
from acme.om.workspaces.types.egress import (
    READ_ONLY,
    EgressAllowlist,
    EgressDecision,
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
from acme.om.workspaces.types.workspace import SessionWorkspace

Network = IPv4Network | IPv6Network

BRANCH_PREFIX = "sessions"
"""Where every session's branch sits on its repository."""

SNAPSHOT_PREFIX = "refs/snapshots"
"""Where a release pushes the work a loop left uncommitted, beside the
branches and never on one."""

COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
"""A commit's full id, SHA-1 or SHA-256, as git prints it."""

PUSH_TOKEN_PREFIX = "spt_"
"""What a session's push token starts with, apart from every other kind of
credential the platform mints."""

NEVER_REACHED: tuple[Network, ...] = tuple(
    ip_network(cidr)
    for cidr in (
        "169.254.0.0/16",  # link-local, the clouds' metadata endpoint among it
        "fe80::/10",
        "fd00:ec2::254/128",  # a cloud's metadata endpoint over IPv6
        "fd20:ce::254/128",  # another cloud's, over IPv6
        "100.100.100.200/32",  # another cloud's metadata endpoint
        "127.0.0.0/8",  # the host itself
        "::1/128",
        "0.0.0.0/8",
        "::/128",
    )
)
"""What no workspace reaches, whatever its egress: the metadata endpoints and
the host it runs on."""

NAT64 = ip_network("64:ff9b::/96")
"""The well-known prefix a NAT64 gateway carries an IPv4 address in."""

METADATA_NAMES = frozenset(
    {"metadata", "metadata.google.internal", "instance-data", "instance-data.ec2.internal"}
)
"""The names the clouds give their metadata endpoints."""

PLATFORM_NETWORKS: tuple[str, ...] = (
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
    "fc00::/7",
)
"""The platform's internal network, by default every private range: a
deployment narrows it to its own (`WorkspacesOptions.internal_networks`)."""


def networks(cidrs: Sequence[str]) -> tuple[Network, ...]:
    return tuple(ip_network(cidr) for cidr in cidrs)


def session_branch(session_id: UUID) -> str:
    """The session's branch on its project's repository."""
    return f"{BRANCH_PREFIX}/{session_id}"


def snapshot_ref(branch: str, at: datetime) -> str:
    """The ref one release's snapshot of `branch` is pushed to."""
    return f"{SNAPSHOT_PREFIX}/{branch}/{at:%Y%m%dT%H%M%S%fZ}"


def snapshot_at(ref: str) -> datetime | None:
    """When the snapshot `snapshot_ref` named was taken, in UTC; None for a
    ref it did not name."""
    try:
        return datetime.strptime(ref.rsplit("/", 1)[-1], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
    except ValueError:
        return None


# The egress a session pins.


def pinned_egress(
    kind: EgressPolicy, kind_name: str, allowlist: EgressAllowlist | None
) -> tuple[EgressMode, tuple[EgressRule, ...], str]:
    """The egress a new session pins, its rules, and where it came from. A
    kind that takes no egress keeps none. Otherwise the project's allowlist
    decides: its rules, or open egress where it chose it, or none where it
    names nothing. A session of no project keeps its kind's own: open egress
    where the kind declares it, and the hosts it names, read-only, since a
    kind's hosts carry no method."""
    if kind.mode is EgressMode.NONE:
        return EgressMode.NONE, (), f"its kind {kind_name} takes no egress"
    if allowlist is None:
        if kind.mode is EgressMode.OPEN:
            return EgressMode.OPEN, (), f"its kind {kind_name} declares open egress"
        rules = tuple(EgressRule(destination=host, methods=READ_ONLY) for host in kind.hosts)
        return EgressMode.ALLOWLIST, rules, f"its kind {kind_name} names its hosts, read-only"
    source = f"project {allowlist.project_id}'s allowlist at version {allowlist.version}"
    if allowlist.open:
        return EgressMode.OPEN, (), f"{source}, open: {allowlist.reason}"
    if not allowlist.rules:
        return EgressMode.NONE, (), f"{source}, which names nothing"
    return EgressMode.ALLOWLIST, allowlist.rules, source


# What a host refuses.


def host_refusal(spec: IsolationSpec, offer: HostOffer, *, local: bool, running: int) -> str | None:
    """Why the host that `offer` describes refuses to prepare `spec`, with
    `running` other sessions' workspaces live on it; None when it may, and
    its provider decides the rest. In `local`, the developer's own machine,
    the provider alone decides, as the twin's level and an account's are
    local's alone."""
    if spec.mode is IsolationMode.NONE or local:
        return None
    if spec.mode is IsolationMode.TWIN:
        return "a twin plays a workspace in local alone"
    if spec.mode is IsolationMode.ACCOUNT:
        return "an account of the host runs a workspace in local alone"
    if spec.mode is IsolationMode.HOST:
        if not offer.inside_wall:
            return "a bare directory runs only inside a customer's wall"
        if not offer.dedicated_user:
            return "a bare directory runs only as a dedicated, unprivileged user"
        if offer.directory_only and running >= offer.directory_sessions:
            return f"this host runs {offer.directory_sessions} directory session(s) at once"
    if spec.egress.mode is not EgressMode.NONE and not offer.blocks_internal:
        return "this host cannot keep a workspace's egress off the platform's insides"
    if spec.egress.mode is EgressMode.ALLOWLIST and not offer.enforces_allowlist:
        return "this host cannot hold an allowlist's destinations and methods"
    return None


# The egress proxy's answer.


def _address(value: IPv4Address | IPv6Address) -> IPv4Address | IPv6Address:
    """An IPv4 address carried in IPv6 is the IPv4 address it carries: mapped,
    through 6to4, or through a NAT64 gateway's prefix."""
    if not isinstance(value, IPv6Address):
        return value
    if value.ipv4_mapped is not None:
        return value.ipv4_mapped
    if value.sixtofour is not None:
        return value.sixtofour
    if value in NAT64:
        return IPv4Address(int(value) & 0xFFFFFFFF)
    return value


def walled(address: str, walls: Sequence[Network]) -> bool:
    """Whether `address`, as a resolver answers it, is inside one of
    `walls`: an IPv4 address carried in IPv6 counts as the one it carries."""
    return any(_address(ip_address(address)) in network for network in walls)


def _literal(name: str) -> IPv4Address | IPv6Address | None:
    try:
        return _address(ip_address(name.strip("[]")))
    except ValueError:
        return None


def _matches(rule: EgressRule, name: str, port: int) -> bool:
    if rule.port != port:
        return False
    if rule.destination.startswith("*."):
        return name.endswith(rule.destination[1:])
    return name == rule.destination


def egress_decision(
    egress: EgressMode,
    rules: Sequence[EgressRule],
    request: EgressRequest,
    internal: Sequence[Network],
) -> EgressDecision:
    """The answer the egress proxy gives one connection of a workspace whose
    pinned egress is `egress` with `rules`. What it connects to is checked
    first, by the address its name resolved to and by the name: a metadata
    endpoint, the host itself, and the platform's internal network are never
    reached, under any egress. Then no egress refuses all, open egress
    allows the rest, and an allowlist allows a destination and port it
    names, by a method that rule takes."""
    name = request.destination.lower().rstrip(".")
    for address in (_address(request.address), _literal(name)):
        if address is None:
            continue
        if any(address in network for network in NEVER_REACHED):
            return EgressDecision(allowed=False, reason=f"{address} is never reached")
        if any(address in network for network in internal):
            return EgressDecision(allowed=False, reason=f"{address} is the platform's own")
    if name in METADATA_NAMES:
        return EgressDecision(allowed=False, reason=f"{name} is a metadata endpoint")
    if egress is EgressMode.NONE:
        return EgressDecision(allowed=False, reason="this workspace has no egress")
    if egress is EgressMode.OPEN:
        return EgressDecision(allowed=True, reason="open egress, a recorded choice")
    matched = [rule for rule in rules if _matches(rule, name, request.port)]
    if not matched:
        return EgressDecision(
            allowed=False, reason=f"{name}:{request.port} is not on the allowlist"
        )
    if request.method is None:
        return EgressDecision(allowed=False, reason=f"a request to {name} names no method")
    if not any(request.method in rule.methods for rule in matched):
        return EgressDecision(
            allowed=False, reason=f"{request.method.value} is not allowed to {name}"
        )
    return EgressDecision(allowed=True, reason=f"{name} takes {request.method.value}")


# The session's branch at a prepare.


def branch_plan(state: BranchState, *, seen: bool, fate: PullRequestFate | None) -> BranchPlan:
    """What a prepare does with the session's branch. One the remote holds is
    tracked. One the remote never held is kept where the checkout holds it,
    and cut where nothing does: from its last snapshot, which holds its
    commits and the work left uncommitted, or from the default branch when
    it has none. One the remote held and lost is rebuilt only when its pull
    request was merged or closed; anything else fails, and nothing restarts
    from the default branch. A branch that moved on the remote and in the
    checkout both fails too: nothing merges the two silently."""
    if state.remote:
        return BranchPlan.DIVERGED if state.diverged else BranchPlan.TRACK
    if not seen:
        return BranchPlan.KEEP if state.local else BranchPlan.CUT
    return BranchPlan.LOST if fate is None else BranchPlan.REBUILD


def told_of_rebuild(branch: str, fate: PullRequestFate, base: str | None) -> str:
    cut_from = "the repository's default branch" if base is None else base
    return (
        f"Your branch {branch} was deleted after its pull request was {fate.value}. "
        f"It was cut again from {cut_from}; its commits are in that pull request. "
        "Your base moved: take a baseline with validate, baseline set, before you validate "
        "your next change."
    )


def told_of_snapshot(ref: str, commit: str, at: datetime) -> str:
    """One instance's work, marked with when it was let go: the next loop
    may be told of several, an older instance's beside a newer one's."""
    return (
        f"When an instance of this workspace was let go at {at:%Y-%m-%d %H:%M:%S} UTC, "
        f"the work not yet committed was committed as {commit} and pushed to {ref}. "
        f"If it is missing here, restore it from there."
    )


# Work product, and what acts outward.


def same_repository(a: str, b: str) -> bool:
    """Whether two ways of naming a repository name the same one: by URL, by
    `host:owner/name`, with or without credentials, `.git`, or case."""
    return _repository(a) == _repository(b)


def _repository(name: str) -> str:
    value = name.strip().lower()
    if "://" in value:
        value = value.split("://", 1)[1]
    elif ":" in value.split("/", 1)[0]:
        value = value.replace(":", "/", 1)
    host, slash, path = value.partition("/")
    value = host.rsplit("@", 1)[-1] + slash + path
    return value.rstrip("/").removesuffix(".git")


def project_key(binding: RepositoryBinding) -> str:
    """The name a project's work product goes by in its evidence: its
    repository's, as `host/owner/name`. The host goes without its port, so a
    forge served on one has a name too."""
    host, slash, path = _repository(binding.repository).lstrip("/").partition("/")
    return host.split(":", 1)[0] + slash + path


FETCHED = re.compile(
    r"!\[|<\s*(?:img|image|picture|source|video|audio|track|iframe|frame|object|embed|svg"
    r"|input|link|meta|style|base)\b",
    re.IGNORECASE,
)
"""What a forge fetches as it renders a body: a Markdown image, and an HTML
element that loads a URL."""
AUTHORITY = re.compile(r"[/\\]{2,}([^\s/\\?#<>()\[\]{}\"'`|]+)")
"""The host a URL names after the slashes that open it, whatever its scheme
or none: a backslash is read as a slash, as a browser reads it."""
SCHEMED = re.compile(r"\b(?:https?|ftps?|wss?):[/\\]*([^\s/\\?#<>()\[\]{}\"'`|]+)", re.IGNORECASE)
"""The host a URL of a scheme a surface fetches names, with any number of
slashes before it, none included, as a browser reads it."""
WWW = re.compile(r"\b(www\.[^\s/\\?#<>()\[\]{}\"'`|]+)", re.IGNORECASE)
"""A host a renderer links without a scheme."""


def body_refusal(body: str, binding: RepositoryBinding) -> str | None:
    """Why a pull request's body is refused, or None. The agent writes it and
    the forge renders it, so nothing in it may make the forge, or a surface
    that mirrors it, fetch a URL the agent chose: it holds no image and no
    element that loads one, and every URL in it, a link's included, is on
    the bound repository's own host. It is read as written and with its
    character references resolved, as a renderer reads it."""
    own_host = project_key(binding).partition("/")[0]
    for text in (body, html.unescape(body)):
        if FETCHED.search(text):
            return "a pull request's body carries no image, and no element that loads a URL"
        for pattern in (AUTHORITY, SCHEMED, WWW):
            for found in pattern.finditer(text):
                host = found.group(1).rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".").lower()
                if not own_host or host != own_host:
                    return (
                        f"a pull request's body links only to its repository's host, "
                        f"never to {host[:100]}"
                    )
    return None


def is_work_product(write: RepositoryWrite, binding: RepositoryBinding | None, branch: str) -> bool:
    """Whether a write is the session's own work product: a push to its own
    branch, or to a snapshot of it, and its own pull request, on the one
    repository its project binds. Every other write acts outward, and so
    does every write of a session whose project binds none."""
    if binding is None or not same_repository(write.repository, binding.repository):
        return False
    ref = write.ref.removeprefix("refs/heads/")
    if write.kind is WriteKind.PUSH:
        return ref == branch or write.ref.startswith(f"{SNAPSHOT_PREFIX}/{branch}/")
    if write.kind is WriteKind.PULL_REQUEST:
        return ref == branch
    return False


# The credentials a repository is reached with.


def fetch_secret_name(project_id: UUID) -> str:
    """The name the tenant's store keeps a project's fetch credential under:
    apart from every declared secret's (`project-`) and every
    provider key's (`provider-key-`)."""
    return f"repository-fetch-{project_id.hex}"


def push_refusal(
    held: SessionWorkspace,
    binding: RepositoryBinding | None,
    digest: str,
    write: RepositoryWrite,
    now: datetime,
) -> str | None:
    """Why a push token, by its digest, does not make `write` for the session
    whose workspace is `held`; None when it does. It makes only the session's
    own work product (`is_work_product`), and only while it is the loop's
    live token and has not expired."""
    live = held.push_digest
    if live is None or not hmac.compare_digest(live, digest):
        return "the push token is not the live token of this session's loop"
    if held.push_expires_at is None or now >= held.push_expires_at:
        return "the push token has expired"
    if not is_work_product(write, binding, held.branch):
        return f"the push token writes {held.branch} and its pull request on its repository alone"
    return None
