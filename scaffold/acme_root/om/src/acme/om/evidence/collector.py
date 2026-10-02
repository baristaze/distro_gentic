"""The one collector: every place a check runs writes the same results
stream, and this reads it, one line as each case finishes. It is strict:
a line it cannot read, a schema it does not know, a field it does not
expect, or a run left open refuses the whole stream."""

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from acme.om.base import new_id
from acme.om.evidence.types.contract import (
    SCHEMAS,
    CaseLine,
    CaseOutcome,
    EndLine,
    ResultsLine,
    StartLine,
)
from acme.om.evidence.types.record import CaseTally, ExecutionRecord, RunPurpose
from acme.om.exceptions import ValidationFailed

LINE: TypeAdapter[StartLine | CaseLine | EndLine] = TypeAdapter(ResultsLine)


def digest(results: bytes) -> str:
    return hashlib.sha256(results).hexdigest()


class Collector:
    """Reads one results stream into execution records. Each record names
    who wrote the stream (`executor`) and why it ran; the rest comes from
    the stream. `feed` takes one line and answers the case it held, so a
    viewer sees each case as it finishes."""

    def __init__(
        self,
        *,
        executor: str,
        session_id: UUID,
        project: str,
        purpose: RunPurpose,
        validation_id: UUID | None,
        now: datetime,
        ids: Callable[[], UUID] = new_id,
    ) -> None:
        self._base = {
            "executor": executor,
            "session_id": session_id,
            "project": project,
            "purpose": purpose,
            "validation_id": validation_id,
            "created_at": now,
        }
        self._ids = ids
        self._start: StartLine | None = None
        self._cases = {outcome: 0 for outcome in CaseOutcome}
        self._records: list[ExecutionRecord] = []
        self._lines = 0

    def feed(self, line: str | bytes) -> CaseLine | None:
        self._lines += 1
        try:
            text = line.decode() if isinstance(line, bytes) else line
            if not text.strip():
                return None
            raw = json.loads(text)
            if isinstance(raw, dict) and raw.get("kind") == "start":
                schema = raw.get("schema_version")
                if schema not in SCHEMAS:
                    raise self._refused(f"results schema {schema!r} is not one this platform reads")
            found = LINE.validate_json(text, strict=True)
        except (ValueError, ValidationError) as error:
            raise self._refused(f"{type(error).__name__}: {error}") from None
        match found:
            case StartLine():
                if self._start is not None:
                    raise self._refused("a run starts before the last one ended")
                self._start = found
                self._cases = {outcome: 0 for outcome in CaseOutcome}
                return None
            case CaseLine():
                if self._start is None:
                    raise self._refused("a case arrives outside a run")
                self._cases[found.outcome] += 1
                return found
            case EndLine():
                self._end(found)
                return None

    def records(self) -> tuple[ExecutionRecord, ...]:
        """The records the stream held, once it ended with every run closed."""
        if self._start is not None:
            raise self._refused("the stream ends with a run still open")
        return tuple(self._records)

    def _end(self, end: EndLine) -> None:
        start = self._start
        if start is None:
            raise self._refused("a run ends that never started")
        try:
            record = ExecutionRecord(
                id=self._ids(),
                **self._base,
                version=start.version,
                dirty=start.dirty,
                environment=start.environment,
                host=start.host,
                isolation=start.isolation,
                check=start.check,
                check_version=start.check_version,
                parameters=start.parameters,
                metrics=end.metrics,
                started_at=start.started_at,
                finished_at=end.finished_at,
                outcome=end.outcome,
                cases=CaseTally(
                    passed=self._cases[CaseOutcome.PASSED],
                    failed=self._cases[CaseOutcome.FAILED],
                    skipped=self._cases[CaseOutcome.SKIPPED],
                ),
                artifacts=end.artifacts,
                dependencies=start.dependencies,
                abort=end.abort,
            )
        except ValidationError as error:
            raise self._refused(f"the run does not hold together: {error}") from None
        self._records.append(record)
        self._start = None

    def _refused(self, why: str) -> ValidationFailed:
        return ValidationFailed(f"results line {self._lines}: {why}")


def collect(
    results: bytes,
    *,
    executor: str,
    session_id: UUID,
    project: str,
    purpose: RunPurpose,
    validation_id: UUID | None,
    now: datetime,
    ids: Callable[[], UUID] = new_id,
) -> tuple[ExecutionRecord, ...]:
    """A whole results stream, read as the collector reads it line by line."""
    collector = Collector(
        executor=executor,
        session_id=session_id,
        project=project,
        purpose=purpose,
        validation_id=validation_id,
        now=now,
        ids=ids,
    )
    for line in _lines(results):
        collector.feed(line)
    return collector.records()


def _lines(results: bytes) -> Iterable[bytes]:
    return results.splitlines()
