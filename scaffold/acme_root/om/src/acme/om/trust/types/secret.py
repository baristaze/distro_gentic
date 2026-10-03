"""An environment secret, as the platform knows it: by name, never by
value. It is declared on a project, with the variable a command sees,
the scope the credential is minted for, and the store that holds its
value: the platform's, in its cloud, or the store of the machine that
executes the call, inside a customer's wall. The value lives only in
that store; the platform keeps the declaration. A name is one owner's:
each project declares its own secret of a name, and keeps its own value."""

from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from acme.infra.transports import ENV_NAME
from acme.om.base import Identifiable, Trackable
from acme.om.steps.types.content import MAX_NAME, Stored

SECRET_NAME = r"^[^/\s][^/]*$"
"""A secret's name is one segment, as a store keys it under its tenant."""


class SecretOwnerKind(StrEnum):
    """What a secret is declared on."""

    PROJECT = "project"


class SecretStore(StrEnum):
    """Where a secret's value is held, and so where it is resolved."""

    CLOUD = "cloud"  # the platform's store, in its cloud: never sent to a customer's host
    HOST = "host"  # the executing machine's own store, inside a customer's wall


class SecretDeclaration(Identifiable, Trackable):
    """A secret by name: what a command that uses it sees it as, what it may
    do, and which store holds it. No field holds its value."""

    MANAGER_OWNED_FIELDS: ClassVar[tuple[str, ...]] = ()

    name: Stored = Field(min_length=1, max_length=MAX_NAME, pattern=SECRET_NAME)
    variable: str = Field(min_length=1, max_length=MAX_NAME, pattern=ENV_NAME.pattern)
    owner_kind: SecretOwnerKind
    owner_id: UUID
    scope: Stored = Field(min_length=1, max_length=MAX_NAME)
    store: SecretStore


def kept_as(declaration: SecretDeclaration) -> str:
    """The name the tenant's store keeps a declared secret's value under:
    under its owner, so each project keeps its own value of one name, apart
    from the tenant's own and from every other project's."""
    return f"{declaration.owner_kind.value}-{declaration.owner_id.hex}-{declaration.name}"
