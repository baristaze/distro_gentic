"""The evidence swimlane: what makes a result. Every execution is a record
of the version and the environment it ran in, with the provenance of each
dependency; hypotheses and findings are records linked to the runs that
show them. Each project declares a validation policy and the paths the
agent may not change. Validation runs on a fresh executor, never in the
agent's workspace, and the result gate (`impl/gate.py`) accepts a success
only on the runs that executor wrote at the head delivered."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from acme.om.context import TenantContext
from acme.om.evidence.types.inference import Inference, InferencePage
from acme.om.evidence.types.policy import ValidationPolicy
from acme.om.evidence.types.record import ExecutionRecord, ExecutionRecordPage, RunPurpose
from acme.om.evidence.types.validation import Validation
from acme.om.tools.types.policy import Target


class EvidenceManagerInterface(ABC):
    # The policy.

    @abstractmethod
    async def get_policy(self, ctx: TenantContext, project: str) -> ValidationPolicy:
        """The validation policy kept under `project`, a project's id
        (`rules.policy_key`); `NotFound` when it declares none."""
        ...

    @abstractmethod
    async def write_policy(self, ctx: TenantContext, policy: ValidationPolicy) -> ValidationPolicy:
        """Declares or changes a project's policy, as a person who manages
        the tenant: a service, and so an agent, is `NotAuthorized`. A write
        after the create names the version it read (`PreconditionFailed`
        otherwise), and the version is the manager's."""
        ...

    @abstractmethod
    async def protection(
        self, ctx: TenantContext, session_id: UUID, paths: Sequence[str]
    ) -> Target:
        """What a call of the session that changes `paths` acts on, for
        policy to read: whether the policy of the session's project, as the
        projects answer it, protects any of them. A session of no project,
        or of one with no policy, has nothing protected. A tool that changes
        files reports it as its target, and the platform's ceiling denies
        the call (`rules.PROTECTED_CEILING`), or refuses the call itself."""
        ...

    # The runs.

    @abstractmethod
    async def record_run(self, ctx: TenantContext, record: ExecutionRecord) -> ExecutionRecord:
        """Keeps one of the agent's own runs, written once. Only the executor
        writes a baseline or a validation: such a record here is
        `ValidationFailed`."""
        ...

    @abstractmethod
    async def get_runs(
        self, ctx: TenantContext, session_id: UUID, after: UUID | None, limit: int
    ) -> ExecutionRecordPage:
        """One page of the session's runs, oldest first, strictly after
        `after`; `limit` is clamped."""
        ...

    @abstractmethod
    async def record_inference(self, ctx: TenantContext, inference: Inference) -> Inference:
        """Keeps a hypothesis or a finding, written once. Every run it cites
        is a run of its session, and the hypothesis a finding resolves is
        one of its session's hypotheses; otherwise `ValidationFailed`."""
        ...

    @abstractmethod
    async def get_inferences(
        self, ctx: TenantContext, session_id: UUID, after: UUID | None, limit: int
    ) -> InferencePage:
        """One page of the session's hypotheses and findings, oldest first."""
        ...

    # Validation.

    @abstractmethod
    async def validate(
        self, ctx: TenantContext, session_id: UUID, purpose: RunPurpose
    ) -> Validation:
        """Runs the session's checks on a fresh executor and keeps what it
        wrote: a `validation` at the committed head, of the checks the
        change asks for, or a `baseline` at the base, of every check the
        policy requires. The checks, fixtures, and runner come from the
        base. The policy is the session's project's, as the projects answer
        it, never one the work product names. Refused before anything runs
        (`PreconditionFailed`) when the session holds no work product,
        belongs to no project, its project declares no policy, its
        tree is dirty, its change touches a protected path, nothing is asked
        for, or the executor cannot run a check. Results that do not hash to
        what the executor wrote, or that do not read as the contract says,
        are `ValidationFailed`, and nothing is kept."""
        ...

    @abstractmethod
    async def get_validations(
        self, ctx: TenantContext, session_id: UUID, limit: int
    ) -> tuple[Validation, ...]:
        """The session's validations and baselines, oldest first; `limit` is
        clamped."""
        ...

    # The purges.

    @abstractmethod
    async def purge_session(self, org_id: UUID, session_id: UUID) -> int:
        """Platform-internal: a purged session's runs, validations, and
        hypotheses and findings, under the purge login, in the tenant
        named; for no principal. Returns how many went."""
        ...

    @abstractmethod
    async def purge_tenant(self, ctx: TenantContext) -> int:
        """The sweep, for one tenant past its own retention: its policies,
        then its runs, a batch at most a call. Any other tenant returns 0
        and reads nothing."""
        ...
