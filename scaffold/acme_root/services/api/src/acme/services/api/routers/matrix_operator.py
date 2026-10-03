"""The operators' routes of the model matrix under /v1/admin/matrix: stage
a version, publish it, and read one. Each takes `OperatorContext`; a stage
and a publish need the write permission and a read the read one, and a
tenant's credential never reaches them. The matrix is the platform's, so
no route names a tenant.

A stage is a creating POST and runs under the operator's idempotency
record. A publish changes a version's status alone: a second answers that
it is published already."""

from typing import Annotated

from fastapi import APIRouter, Path, Response

from acme.services.api.gateway.admin import OperatorCtx
from acme.services.api.gateway.idempotency import OperatorIdem
from acme.services.api.gateway.resolve import MatrixService
from acme.services.api.types.matrix import MatrixVersionView, StageRequest

router = APIRouter(prefix="/admin/matrix", tags=["admin"])

Number = Annotated[int, Path(ge=1)]


@router.post("/versions", response_model=MatrixVersionView, status_code=201)
async def stage(
    admin: OperatorCtx, service: MatrixService, body: StageRequest, idem: OperatorIdem
) -> Response:
    """A new pending version, numbered after the last. Its shape is checked
    here, its fills when it is published."""
    return await idem.run(201, lambda _attempt: service.stage(admin, body))


@router.post("/versions/{number}/publish", response_model=MatrixVersionView)
async def publish(admin: OperatorCtx, service: MatrixService, number: Number) -> MatrixVersionView:
    """The pending version, published: every session resolved from now on
    is pinned to it, and a running one keeps the version it holds.
    `validation_failed` names every reason it may not be: no row matches
    every question, or a fill is unpriced, unqualified for a model role its
    row serves, or retired."""
    return await service.publish(admin, number)


@router.get("/versions/current", response_model=MatrixVersionView)
async def get_current(admin: OperatorCtx, service: MatrixService) -> MatrixVersionView:
    """The latest version published: the matrix."""
    return await service.get_version(admin, None)


@router.get("/versions/{number}", response_model=MatrixVersionView)
async def get_version(
    admin: OperatorCtx, service: MatrixService, number: Number
) -> MatrixVersionView:
    return await service.get_version(admin, number)
