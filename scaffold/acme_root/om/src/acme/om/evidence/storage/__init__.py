"""Storage of the evidence swimlane. Every operation takes org_id first.

A project's validation policy is one row in `core`, written by a
compare-and-set on its version with its outbox rows in one commit. The
runs, the validations, and the hypotheses and findings are written once,
in `activity`: the serving logins hold SELECT and INSERT on them, and the
purge login takes them with their session or their tenant (ADR 1002, ADR
1010). There is no update of a run and no delete but the purges."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.evidence.types.inference import Inference
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.record import ExecutionRecord
from acme.om.evidence.types.validation import Validation
from acme.om.outbox.types.row import OutboxRow


class EvidenceStorageInterface(ABC):
    # The policies.

    @abstractmethod
    async def read_policy(self, org_id: UUID, project: str) -> ValidationPolicy | None:
        """The project's policy, or None when it has never written one."""
        ...

    @abstractmethod
    async def create_policy(
        self, org_id: UUID, policy: ValidationPolicy, outbox_rows: tuple[OutboxRow, ...]
    ) -> bool:
        """The create, with the rows that announce it, in one commit; False,
        with nothing landed, when the id is written already.
        `UniqueKeyTaken` when the project holds another policy already."""
        ...

    @abstractmethod
    async def write_policy(
        self,
        org_id: UUID,
        policy: ValidationPolicy,
        expected_version: int,
        outbox_rows: tuple[OutboxRow, ...],
    ) -> None:
        """The compare-and-set: lands the policy and its outbox rows together
        when the stored one is at `expected_version`, and raises
        `PreconditionFailed` otherwise, landing nothing."""
        ...

    # The runs, written once.

    @abstractmethod
    async def create_record(self, org_id: UUID, record: ExecutionRecord) -> bool:
        """One run; False, with nothing written, when its id is written
        already."""
        ...

    @abstractmethod
    async def create_validation(
        self, org_id: UUID, validation: Validation, records: Sequence[ExecutionRecord]
    ) -> bool:
        """A validation and every run it lists, in one commit, or nothing:
        False when its id is written already."""
        ...

    @abstractmethod
    async def create_inference(self, org_id: UUID, inference: Inference) -> bool:
        """One hypothesis or finding; False when its id is written already."""
        ...

    @abstractmethod
    async def read_records(
        self, org_id: UUID, session_id: UUID, after: UUID | None, limit: int
    ) -> list[ExecutionRecord]:
        """The session's runs by id, strictly after `after`, at most `limit`."""
        ...

    @abstractmethod
    async def read_cited(
        self, org_id: UUID, session_id: UUID, ids: Sequence[UUID], limit: int
    ) -> list[ExecutionRecord]:
        """The session's runs a citation names: by their own id, the id of the
        agent's step that ran them, or the id of the validation that ran
        them; by id, at most `limit`."""
        ...

    @abstractmethod
    async def read_validations(
        self, org_id: UUID, session_id: UUID, version: str | None, limit: int
    ) -> list[Validation]:
        """The session's validations by id, oldest first, at `version` when
        one is named, at most `limit`."""
        ...

    @abstractmethod
    async def read_validation_records(
        self, org_id: UUID, session_id: UUID, validation_ids: Sequence[UUID], limit: int
    ) -> list[ExecutionRecord]:
        """Every run of the session that names one of these validations, by
        id, at most `limit`."""
        ...

    @abstractmethod
    async def read_inferences(
        self, org_id: UUID, session_id: UUID, after: UUID | None, limit: int
    ) -> list[Inference]:
        """The session's hypotheses and findings by id, strictly after
        `after`, at most `limit`."""
        ...

    @abstractmethod
    async def read_inference(self, org_id: UUID, inference_id: UUID) -> Inference | None:
        """One hypothesis or finding, or None when the tenant holds none by
        that id."""
        ...

    # The purges.

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID, limit: int) -> int:
        """At most `limit` rows of each of a purged session's runs,
        validations, and hypotheses and findings, under the purge login;
        returns how many went."""
        ...

    @abstractmethod
    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        """At most `limit` rows of each table of a deleted tenant past its
        retention: its policies under the serving login, then its runs,
        validations, and hypotheses and findings under the purge login;
        returns how many went."""
        ...
