"""The wire types of a session's evidence and its delivery: each run of a
check it recorded or the executor ran for it, each validation, and what it
delivered (its branch, its pull requests, and the result it submitted).
A run's parameters, its toolchain, and its artifacts stay in the record;
the view carries what a reader judges a run by."""

from datetime import datetime
from uuid import UUID

from acme.om.evidence.types.provenance import Provenance
from acme.om.evidence.types.record import RunOutcome, RunPurpose
from acme.om.intake.types.link import HandleKind
from acme.om.steps.types.header import LoopOutcome
from acme.services.api.types.common import View


class CasesView(View):
    passed: int
    failed: int
    skipped: int


class ExecutionView(View):
    """One run of one check: why it ran, the version and whether the tree
    was dirty, the image, host, and isolation it ran on, who wrote its
    results, its timing, its outcome and its cases, and the weakest
    provenance of what served it. A `work` run names the agent's tool call;
    a baseline or a validation run names its validation."""

    id: UUID
    purpose: RunPurpose
    step_id: UUID | None
    validation_id: UUID | None
    project: str
    version: str
    dirty: bool
    image: str
    host: str
    isolation: str
    executor: str
    check: str
    check_version: str
    started_at: datetime
    finished_at: datetime
    outcome: RunOutcome
    cases: CasesView
    provenance: Provenance
    abort: str | None


class ExecutionPageView(View):
    """One page of a session's runs, oldest first. `next_cursor` fetches the
    next page and is null on the last one."""

    items: list[ExecutionView]
    next_cursor: str | None


class ValidationView(View):
    """One pass of the policy's checks on a fresh executor: the version it
    ran at and the version its checks came from, who ran it, the hash of
    the results it wrote, and its runs."""

    id: UUID
    created_at: datetime
    purpose: RunPurpose
    project: str
    version: str
    source: str
    executor: str
    results_sha256: str
    records: list[UUID]


class WorkHandleView(View):
    """A pull request or a branch the session opened as its work, by the
    name source control gives it."""

    kind: HandleKind
    handle: str
    bound_at: datetime


class ReportView(View):
    """The result the session submitted and the gate accepted: the outcome
    its loop ended with, whether a gate that knows the evidence judged it,
    and the step that answered it."""

    seq: int
    accepted_at: datetime
    outcome: LoopOutcome
    verified: bool


class DeliveryView(View):
    """What a session delivered: its project, its branch and whether the
    remote has held it, the pull requests and branches bound to it, and its
    latest accepted result. A session that never had a workspace has no
    branch."""

    project_id: UUID | None
    branch: str | None
    branch_seen: bool
    work: list[WorkHandleView]
    report: ReportView | None
