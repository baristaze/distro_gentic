"""An environment secret, as the platform knows it: by name, never by
value. It is declared on a project or a station, with the variable a
command sees, the scope the credential is minted for, and the store that
holds its value: the platform's, in its cloud, or the store of the machine
that executes the call, inside a customer's wall. The value lives only in
that store; the platform keeps the declaration."""

from enum import StrEnum
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator

from acme.infra.transports import ENV_NAME
from acme.om.base import Identifiable, Trackable
from acme.om.steps.types.content import MAX_NAME, Stored

SECRET_NAME = r"^[^/\s][^/]*$"
"""A secret's name is one segment, as a store keys it under its tenant."""


class SecretOwnerKind(StrEnum):
    """What a secret is declared on."""

    PROJECT = "project"
    STATION = "station"


class SecretStore(StrEnum):
    """Where a secret's value is held, and so where it is resolved."""

    CLOUD = "cloud"  # the platform's store, in its cloud: never sent to a customer's host
    HOST = "host"  # the executing machine's own store, inside a customer's wall


class SecretDeclaration(Identifiable, Trackable):
    """A secret by name: what a command that uses it sees it as, what it may
    do, and which store holds it. No field holds its value.

    A station's secret is held on its station's host, so it is declared in
    the host's store and never in the cloud's."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ()

    name: Stored = Field(min_length=1, max_length=MAX_NAME, pattern=SECRET_NAME)
    variable: str = Field(min_length=1, max_length=MAX_NAME, pattern=ENV_NAME.pattern)
    owner_kind: SecretOwnerKind
    owner_id: UUID
    scope: Stored = Field(min_length=1, max_length=MAX_NAME)
    store: SecretStore

    @model_validator(mode="after")
    def _a_station_keeps_its_secrets(self) -> Self:
        if self.owner_kind is SecretOwnerKind.STATION and self.store is not SecretStore.HOST:
            raise ValueError("a station's secret is held on its host, never in the cloud")
        return self
