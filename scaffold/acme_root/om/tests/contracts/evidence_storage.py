"""The evidence storage contract: each project's validation policy, and the
runs, validations, and hypotheses and findings, written once. The cases
named in `CROSS_TENANT_CASES` are the tenant fence's evidence: each one
presents another tenant's identifier and asserts that nothing is found and
nothing changes."""

from datetime import timedelta
from uuid import UUID

import pytest

from acme.om.base import new_id, utcnow
from acme.om.evidence.storage import EvidenceStorageInterface
from acme.om.evidence.types.contract import CheckDeclaration
from acme.om.evidence.types.inference import Inference, InferenceKind, Stance
from acme.om.evidence.types.policy import Requirement, ValidationPolicy
from acme.om.evidence.types.provenance import ArtifactRef, Dependency, Provenance
from acme.om.evidence.types.record import (
    CaseTally,
    Environment,
    ExecutionRecord,
    RunOutcome,
    RunPurpose,
)
from acme.om.evidence.types.validation import Validation
from acme.om.exceptions import PreconditionFailed, UniqueKeyTaken

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "create_inference",
        "create_policy",
        "create_record",
        "create_validation",
        "purge_session",
        "purge_tenant",
        "read_cited",
        "read_inference",
        "read_inferences",
        "read_policy",
        "read_records",
        "read_validation_records",
        "read_validations",
        "write_policy",
    }
)
"""Every method of `EvidenceStorageInterface` that takes a tenant has a case
in this module that presents another tenant's."""

HASH = "ab" * 32


def make_policy(project: str = "arm") -> ValidationPolicy:
    now = utcnow()
    actor = new_id()
    return ValidationPolicy(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=actor,
        updated_by=actor,
        project=project,
        checks=(
            CheckDeclaration(
                name="unit",
                version="1",
                command=("pytest", "--out", "{out}"),
                kind="suite",
                schema_version=1,
            ),
        ),
        requirements=(Requirement(check="unit", paths=("src/**",)),),
        protected=("tests/**", "pytest.ini"),
    )


def make_record(
    session_id: UUID,
    *,
    purpose: RunPurpose = RunPurpose.WORK,
    validation_id: UUID | None = None,
    step_id: UUID | None = None,
    check: str = "unit",
    outcome: RunOutcome = RunOutcome.PASSED,
    provenance: Provenance = Provenance.REAL,
    executor: str = "workspace-1",
    version: str = "c0ffee",
) -> ExecutionRecord:
    now = utcnow()
    return ExecutionRecord(
        id=new_id(),
        created_at=now,
        session_id=session_id,
        project="arm",
        purpose=purpose,
        step_id=step_id,
        validation_id=validation_id,
        version=version,
        dirty=False,
        environment=Environment(image="sha256:" + "1" * 64, toolchain={"python": "3.14"}),
        host="host-1",
        isolation="vm",
        executor=executor,
        check=check,
        check_version="1",
        parameters={"seed": 7},
        metrics={"seconds": 1.5},
        started_at=now - timedelta(seconds=2),
        finished_at=now,
        outcome=outcome,
        cases=CaseTally(
            passed=int(outcome is RunOutcome.PASSED), failed=int(outcome is RunOutcome.FAILED)
        ),
        artifacts=(ArtifactRef(name="log.txt", sha256=HASH, provenance=Provenance.REAL),),
        dependencies=(Dependency(name="arm", provenance=provenance),),
        abort="the guard stopped it" if outcome is RunOutcome.ABORTED else None,
    )


def make_validation(
    session_id: UUID, *runs: int, version: str = "c0ffee", executor: str = "executor-1"
) -> tuple[Validation, tuple[ExecutionRecord, ...]]:
    validation_id = new_id()
    records = tuple(
        make_record(
            session_id,
            purpose=RunPurpose.VALIDATION,
            validation_id=validation_id,
            executor=executor,
            version=version,
        )
        for _ in range(runs[0] if runs else 1)
    )
    validation = Validation(
        id=validation_id,
        created_at=utcnow(),
        session_id=session_id,
        project="arm",
        purpose=RunPurpose.VALIDATION,
        version=version,
        source="base0",
        executor=executor,
        results_sha256=HASH,
        records=tuple(record.id for record in records),
    )
    return validation, records


def make_hypothesis(session_id: UUID) -> Inference:
    return Inference(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id,
        step_id=new_id(),
        kind=InferenceKind.HYPOTHESIS,
    )


def make_finding(session_id: UUID, resolves: UUID, run: UUID) -> Inference:
    return Inference(
        id=new_id(),
        created_at=utcnow(),
        session_id=session_id,
        step_id=new_id(),
        kind=InferenceKind.FINDING,
        resolves=resolves,
        stance=Stance.SUPPORTED,
        supports=(run,),
    )


class EvidenceStorageContract:
    @pytest.fixture
    def storage(self) -> EvidenceStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    # The policies.

    async def test_a_policy_round_trips(self, storage: EvidenceStorageInterface) -> None:
        org = new_id()
        assert await storage.read_policy(org, "arm") is None
        policy = make_policy()
        assert await storage.create_policy(org, policy, ())
        assert await storage.read_policy(org, "arm") == policy
        assert await storage.read_policy(org, "other") is None

    async def test_a_project_holds_one_policy(self, storage: EvidenceStorageInterface) -> None:
        org = new_id()
        first = make_policy()
        assert await storage.create_policy(org, first, ())
        assert not await storage.create_policy(org, first, ()), "the same id is a retry"
        with pytest.raises(UniqueKeyTaken):
            await storage.create_policy(org, make_policy(), ())
        assert await storage.create_policy(org, make_policy("leg"), ())
        assert await storage.read_policy(org, "arm") == first

    async def test_create_policy_under_another_tenant_is_not_read_here(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        policy = make_policy()
        assert await storage.create_policy(org_a, policy, ())
        assert not await storage.create_policy(org_b, policy, ())
        assert await storage.read_policy(org_b, "arm") is None

    async def test_read_policy_of_another_tenant_finds_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        assert await storage.create_policy(new_id(), make_policy(), ())
        assert await storage.read_policy(new_id(), "arm") is None

    async def test_write_policy_is_a_compare_and_set(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org = new_id()
        policy = make_policy()
        assert await storage.create_policy(org, policy, ())
        moved = policy.model_copy(update={"protected": ("**",), "version": 2})
        await storage.write_policy(org, moved, 1, ())
        assert await storage.read_policy(org, "arm") == moved
        with pytest.raises(PreconditionFailed):
            await storage.write_policy(org, moved.model_copy(update={"version": 3}), 1, ())
        assert await storage.read_policy(org, "arm") == moved

    async def test_write_policy_of_another_tenant_changes_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        policy = make_policy()
        assert await storage.create_policy(org_a, policy, ())
        with pytest.raises(PreconditionFailed):
            await storage.write_policy(org_b, policy.model_copy(update={"version": 2}), 1, ())
        assert await storage.read_policy(org_a, "arm") == policy

    # The runs.

    async def test_a_run_round_trips_with_its_provenance(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        run = make_record(session, provenance=Provenance.TWIN, step_id=new_id())
        assert await storage.create_record(org, run)
        assert not await storage.create_record(org, run), "the same id is a retry"
        (found,) = await storage.read_records(org, session, None, 10)
        assert found == run and found.provenance is Provenance.TWIN

    async def test_create_record_under_another_tenant_is_not_read_here(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org_a, org_b, session = new_id(), new_id(), new_id()
        run = make_record(session)
        assert await storage.create_record(org_a, run)
        assert not await storage.create_record(org_b, run)
        assert await storage.read_records(org_b, session, None, 10) == []

    async def test_read_records_pages_by_id_and_keeps_to_the_session(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        runs = [make_record(session) for _ in range(3)]
        for run in runs:
            assert await storage.create_record(org, run)
        assert await storage.create_record(org, make_record(new_id()))
        first = await storage.read_records(org, session, None, 2)
        assert [run.id for run in first] == [run.id for run in runs[:2]]
        rest = await storage.read_records(org, session, first[-1].id, 10)
        assert [run.id for run in rest] == [runs[2].id]

    async def test_read_records_of_another_tenant_finds_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        session = new_id()
        assert await storage.create_record(new_id(), make_record(session))
        assert await storage.read_records(new_id(), session, None, 10) == []

    async def test_a_citation_finds_a_run_by_its_id_its_step_or_its_validation(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        step = new_id()
        by_step = make_record(session, step_id=step)
        by_id = make_record(session)
        validation, executed = make_validation(session, 2)
        assert await storage.create_record(org, by_step)
        assert await storage.create_record(org, by_id)
        assert await storage.create_validation(org, validation, executed)
        found = await storage.read_cited(org, session, [step, by_id.id, validation.id], 10)
        assert {run.id for run in found} == {by_step.id, by_id.id, *validation.records}
        assert await storage.read_cited(org, new_id(), [by_id.id], 10) == [], "its session only"
        assert len(await storage.read_cited(org, session, [validation.id], 1)) == 1
        assert await storage.read_cited(org, session, [], 10) == []

    async def test_read_cited_of_another_tenant_finds_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        session = new_id()
        run = make_record(session)
        assert await storage.create_record(new_id(), run)
        assert await storage.read_cited(new_id(), session, [run.id], 10) == []

    # Validations.

    async def test_a_validation_lands_with_its_runs(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        validation, runs = make_validation(session, 3)
        assert await storage.create_validation(org, validation, runs)
        assert not await storage.create_validation(org, validation, runs), "a retry"
        assert await storage.read_validations(org, session, None, 10) == [validation]
        assert await storage.read_validations(org, session, "c0ffee", 10) == [validation]
        assert await storage.read_validations(org, session, "other", 10) == []
        found = await storage.read_validation_records(org, session, [validation.id], 10)
        assert [run.id for run in found] == sorted(run.id for run in runs)
        assert await storage.read_validation_records(org, session, [], 10) == []

    async def test_a_validation_whose_run_is_written_already_lands_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        first, runs = make_validation(session, 1)
        assert await storage.create_validation(org, first, runs)
        second = first.model_copy(update={"id": new_id()})
        with pytest.raises(UniqueKeyTaken):
            await storage.create_validation(org, second, runs)
        assert await storage.read_validations(org, session, None, 10) == [first]

    async def test_create_validation_under_another_tenant_is_not_read_here(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org_a, org_b, session = new_id(), new_id(), new_id()
        validation, runs = make_validation(session, 1)
        assert await storage.create_validation(org_a, validation, runs)
        assert await storage.read_validations(org_b, session, None, 10) == []

    async def test_read_validations_of_another_tenant_finds_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        session = new_id()
        validation, runs = make_validation(session, 1)
        assert await storage.create_validation(new_id(), validation, runs)
        assert await storage.read_validations(new_id(), session, None, 10) == []

    async def test_read_validation_records_of_another_tenant_finds_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        session = new_id()
        validation, runs = make_validation(session, 2)
        assert await storage.create_validation(new_id(), validation, runs)
        assert await storage.read_validation_records(new_id(), session, [validation.id], 10) == []

    # Hypotheses and findings.

    async def test_an_inference_round_trips(self, storage: EvidenceStorageInterface) -> None:
        org, session = new_id(), new_id()
        hypothesis = make_hypothesis(session)
        finding = make_finding(session, hypothesis.id, new_id())
        assert await storage.create_inference(org, hypothesis)
        assert await storage.create_inference(org, finding)
        assert not await storage.create_inference(org, finding), "a retry"
        assert await storage.read_inferences(org, session, None, 10) == [hypothesis, finding]
        assert await storage.read_inferences(org, session, hypothesis.id, 10) == [finding]
        assert await storage.read_inference(org, finding.id) == finding

    async def test_create_inference_under_another_tenant_is_not_read_here(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org_a, org_b, session = new_id(), new_id(), new_id()
        hypothesis = make_hypothesis(session)
        assert await storage.create_inference(org_a, hypothesis)
        assert not await storage.create_inference(org_b, hypothesis)
        assert await storage.read_inferences(org_b, session, None, 10) == []

    async def test_read_inferences_of_another_tenant_finds_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        session = new_id()
        assert await storage.create_inference(new_id(), make_hypothesis(session))
        assert await storage.read_inferences(new_id(), session, None, 10) == []

    async def test_read_inference_of_another_tenant_finds_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        hypothesis = make_hypothesis(new_id())
        assert await storage.create_inference(new_id(), hypothesis)
        assert await storage.read_inference(new_id(), hypothesis.id) is None

    # The purges.

    async def test_purge_session_takes_its_runs_and_no_other_sessions(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org, gone, kept = new_id(), new_id(), new_id()
        validation, runs = make_validation(gone, 2)
        assert await storage.create_validation(org, validation, runs)
        assert await storage.create_record(org, make_record(gone))
        assert await storage.create_inference(org, make_hypothesis(gone))
        stays = make_record(kept)
        assert await storage.create_record(org, stays)
        assert await storage.purge_session(org, gone, 10) == 5
        assert await storage.purge_session(org, gone, 10) == 0
        assert await storage.read_records(org, gone, None, 10) == []
        assert await storage.read_validations(org, gone, None, 10) == []
        assert await storage.read_inferences(org, gone, None, 10) == []
        assert await storage.read_records(org, kept, None, 10) == [stays]

    async def test_purge_session_under_another_tenant_takes_nothing(
        self, storage: EvidenceStorageInterface
    ) -> None:
        org, session = new_id(), new_id()
        run = make_record(session)
        assert await storage.create_record(org, run)
        assert await storage.purge_session(new_id(), session, 10) == 0
        assert await storage.read_records(org, session, None, 10) == [run]

    async def test_purge_tenant_takes_the_tenants_rows_and_no_other(
        self, storage: EvidenceStorageInterface
    ) -> None:
        gone, kept, session = new_id(), new_id(), new_id()
        assert await storage.create_policy(gone, make_policy(), ())
        assert await storage.create_record(gone, make_record(session))
        validation, runs = make_validation(session, 1)
        assert await storage.create_validation(gone, validation, runs)
        assert await storage.create_inference(gone, make_hypothesis(session))
        stays = make_policy()
        kept_run = make_record(new_id())
        assert await storage.create_policy(kept, stays, ())
        assert await storage.create_record(kept, kept_run)
        assert await storage.purge_tenant(gone, 10) == 5
        assert await storage.purge_tenant(gone, 10) == 0
        assert await storage.read_policy(gone, "arm") is None
        assert await storage.read_records(gone, session, None, 10) == []
        assert await storage.read_policy(kept, "arm") == stays
        assert await storage.read_records(kept, kept_run.session_id, None, 10) == [kept_run]
