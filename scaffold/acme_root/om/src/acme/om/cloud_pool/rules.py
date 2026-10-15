"""Pure rules of the cloud pool: how its VMs and their snapshots are
named, the key a VM is handed, what a session's spec may ask of the
pool's VMs, and how many warm VMs to start. Values in, values
out; no clock, no storage, no settings."""

import hashlib
import json
import secrets
from uuid import UUID

from acme.infra.agent_workspaces import EgressMode, IsolationMode, IsolationSpec
from acme.infra.agent_workspaces import refusal as infra_refusal
from acme.om.base import EMPTY_UUID

KEY_PREFIX = "hmk_"
"""A VM key's prefix. The pool hands each VM one at its start,
and its host trades it, once, for a host's credential of the session the
VM serves."""

MARK = "p"
"""What follows the VMs' prefix in every name the pool gives: no hex
digit, so no name of the VM workspace provider's, which is the prefix and
hex alone, is ever the pool's."""

HASHED = 16
"""Hex digits of a new VM's random name."""

OWNER = 12
"""Hex digits of a tenant's id, and of a session's, in a snapshot's name:
enough that no two of either share them, few enough that the name fits
where a backend bounds it."""

TAG = 8
"""Hex digits that tell a session's snapshots apart."""


def vm_name(prefix: str) -> str:
    """A new VM's name: random, since a VM is started before the
    session it serves is known, and a session's next VM is another."""
    return f"{prefix}{MARK}{secrets.token_hex(HASHED // 2)}"


def tenant_snapshots(prefix: str, org_id: UUID) -> str:
    """What every snapshot of a tenant's VMs is named from: its purge
    finds them all by it."""
    return f"{prefix}{MARK}{_hashed(org_id)}"


def snapshots_of(prefix: str, org_id: UUID, agent_session_id: UUID) -> str:
    """What every snapshot of a session's VMs is named from: the
    session's purge and its key's revocation find them all by it."""
    return f"{tenant_snapshots(prefix, org_id)}{_hashed(agent_session_id)}-"


def snapshot_name(prefix: str, org_id: UUID, agent_session_id: UUID) -> str:
    """A new snapshot of a session's VM, under the session's names."""
    return snapshots_of(prefix, org_id, agent_session_id) + secrets.token_hex(TAG // 2)


def is_snapshot(prefix: str, name: str) -> bool:
    """Whether a name the pool gave is a snapshot's: a VM's has no
    hyphen past the prefix."""
    return pool_names(prefix, name) and "-" in name[len(prefix) :]


def longest_name(prefix: str) -> str:
    """The longest name the pool gives, which the VMs' probe holds to
    what they can keep."""
    return snapshots_of(prefix, EMPTY_UUID, EMPTY_UUID) + "0" * TAG


def _hashed(id_: UUID) -> str:
    return hashlib.sha256(id_.bytes).hexdigest()[:OWNER]


def pool_names(prefix: str, name: str) -> bool:
    """Whether a name the VMs hold is one the pool gives."""
    return name.startswith(f"{prefix}{MARK}")


def new_key() -> str:
    """A VM's one-use key, in the clear: handed to the VM, never
    kept. The pool keeps its digest."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def seed(api_url: str, key: str) -> bytes:
    """What a VM is handed at its start, as a file only its host reads:
    where the platform answers, and the key its host trades once. Nothing
    else: no credential of the platform's, no model key, no tenant's
    record."""
    return json.dumps({"api_url": api_url, "key": key}, sort_keys=True).encode()


def refusal(
    spec: IsolationSpec,
    *,
    closes_egress: bool,
    limits: frozenset[str],
) -> str | None:
    """Why the pool's VMs cannot hold a session's spec, for good; None
    when they can. A VM's egress is closed at its network, never in its
    guest, whose root its commands hold: an allowlist needs an egress proxy
    no VM runs, and a VMs' backend that closes no egress refuses
    a session that must reach nothing. A limit the backend does not enforce
    is refused, never dropped, and a VM holds whole cpus. A base is not
    built on the pool's VMs: a session starts from the pool's image, or
    from its own snapshot."""
    egress = {EgressMode.OPEN, *((EgressMode.NONE,) if closes_egress else ())}
    why = infra_refusal(spec, mode=IsolationMode.VM, egress=egress, limits=limits)
    if why is not None:
        return why
    cpus = spec.limits.cpus
    if cpus is not None and not float(cpus).is_integer():
        return f"a VM of the cloud pool holds whole cpus, not {cpus}"
    if spec.base is not None:
        return "a session of the cloud pool starts from the pool's image, never from a base"
    return None


def warm_to_start(wanted: int, warm: int) -> int:
    """How many warm VMs to start, so `wanted` stand ahead of demand
    when `warm` stand or start already."""
    return max(0, wanted - warm)
