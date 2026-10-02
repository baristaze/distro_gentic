"""Provenance: what served an execution. Every dependency an execution
relied on, and every artifact it made, says whether it was the real thing,
a twin, a test double, or not there at all. A double is never validation,
and a twin is never reported as real."""

from enum import StrEnum

from pydantic import Field

from acme.om.base import Platform

SHA256 = r"^[0-9a-f]{64}$"
"""A hash as the executor writes it: sha256, lower-case hex."""


class Provenance(StrEnum):
    """From the strongest to the weakest."""

    REAL = "real"  # the system itself
    TWIN = "twin"  # the guideline's twin: a deterministic stand-in that names itself
    DOUBLE = "double"  # a test double: never validation
    UNAVAILABLE = "unavailable"  # the dependency was not there

    @property
    def strength(self) -> int:
        return STRENGTH[self]


STRENGTH = {
    Provenance.REAL: 3,
    Provenance.TWIN: 2,
    Provenance.DOUBLE: 1,
    Provenance.UNAVAILABLE: 0,
}


class Dependency(Platform):
    """One thing an execution relied on, such as a service, a device, or a
    model provider, and what served it."""

    name: str = Field(min_length=1, max_length=200)
    provenance: Provenance


class ArtifactRef(Platform):
    """An artifact an execution made: its name, the hash of its bytes, and
    what made it. The bytes are in the object store, never here."""

    name: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=SHA256)
    provenance: Provenance


def weakest(*provenances: Provenance) -> Provenance:
    """The provenance a run reports: its weakest dependency's, so one twin
    makes the whole run a twin's, and one double a double's. A run that
    relied on nothing outside itself is real."""
    return min(provenances, key=lambda found: found.strength, default=Provenance.REAL)
