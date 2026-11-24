"""Pure rules of the cloud pool: how its VMs are named, the key a VM is
handed, what a session's spec may ask of the pool's VMs and the size it
gets, and how many warm VMs to start. Values in, values out; no clock, no
storage, no settings."""

import json
import secrets
from collections.abc import Collection

from acme.infra.agent_workspaces import EgressMode, IsolationMode, IsolationSpec, VmSize
from acme.infra.agent_workspaces import refusal as infra_refusal

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

DEFAULT_SIZE = VmSize.S
"""The size of a VM whose session's spec asks none, and of every warm
VM: a claim of another size starts a VM of its own."""


def vm_name(prefix: str) -> str:
    """A new VM's name: random, since a VM is started before the
    session it serves is known, and a session's next VM is another."""
    return f"{prefix}{MARK}{secrets.token_hex(HASHED // 2)}"


def longest_name(prefix: str) -> str:
    """The longest name the pool gives, a VM's, which the VMs' probe
    holds to what they can keep. The pool keeps no disk under any name."""
    return f"{prefix}{MARK}" + "0" * HASHED


def new_key() -> str:
    """A VM's one-use key, in the clear: handed to the VM, never
    kept. The pool keeps its digest."""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def seed(api_url: str, key: str, *, warm: bool = False) -> bytes:
    """What a VM is handed at its start, as a file only its host reads:
    where the platform answers, the key its host trades once, and, on a
    warm VM, that no session waits on it yet, so its image reads its hot
    paths before its host asks for one. Nothing else: no credential of
    the platform's, no model key, no tenant's record."""
    handed: dict[str, object] = {"api_url": api_url, "key": key}
    if warm:
        handed["warm"] = True
    return json.dumps(handed, sort_keys=True).encode()


def size_of(spec: IsolationSpec) -> VmSize:
    """The size of the VM a session's spec asks for: its own, else the
    pool's default."""
    return spec.limits.size or DEFAULT_SIZE


def refusal(
    spec: IsolationSpec,
    *,
    closes_egress: bool,
    sizes: Collection[VmSize],
) -> str | None:
    """Why the pool's VMs cannot hold a session's spec, for good; None
    when they can. A VM's egress is closed at its network, never in its
    guest, whose root its commands hold: an allowlist needs an egress proxy
    no VM runs, and a VMs' backend that closes no egress refuses
    a session that must reach nothing. A VM is sized by name, one of the
    `sizes` its deployment allows, never by cpus, memory, or processes,
    which name no machine a cloud runs: any other ask is refused, never
    met with another size. A base is not built on the pool's VMs: a
    session starts from the pool's image, or from its own snapshot. The
    answer names only what the spec declares, so it is the session's to
    read."""
    if raw := sorted(spec.limits.asked() - {"size"}):
        return f"a VM of the cloud pool is sized by name, never by {', '.join(raw)}"
    egress = {EgressMode.OPEN, *((EgressMode.NONE,) if closes_egress else ())}
    why = infra_refusal(spec, mode=IsolationMode.VM, egress=egress, limits=("size",))
    if why is not None:
        return why
    if (size := size_of(spec)) not in sizes:
        return f"the cloud pool runs no VM of size {size.value} here"
    if spec.base is not None:
        return "a session of the cloud pool starts from the pool's image, never from a base"
    return None


def warm_to_start(wanted: int, warm: int, room: int) -> int:
    """How many warm VMs to start, so `wanted` stand ahead of demand
    when `warm` stand or start already, and never past the `room` the
    pool's maximum leaves."""
    return max(0, min(wanted - warm, room))
