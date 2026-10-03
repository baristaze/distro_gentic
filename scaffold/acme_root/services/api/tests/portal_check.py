"""What the portal's browser check needs from the stack, run by the check
itself and by no gate:

    python services/api/tests/portal_check.py script <path>
    python services/api/tests/portal_check.py evidence <slug> <session_id>

`script` writes the scripted provider's script: one turn that answers in
Markdown and calls nothing, so a session runs its loop offline and the same
way every time. `evidence` records on one session of the org what an
executor writes: two runs of a check and a validation of one of them. The
local stack runs no executor, so the check writes the records its evidence
screen reads through the om, under the org's owner."""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

REPO = Path(__file__).resolve().parents[3]

ANSWER = (
    "Done. The docs now read in **one voice**.\n\n"
    "- The README opens on what the product does.\n"
    "- Every command runs as written: `make check`.\n"
)


def write_script(path: Path) -> None:
    from acme.integrations.model_providers.calls import ModelReply
    from acme.integrations.model_providers.content import TextBlock
    from acme.integrations.model_providers.scripted import SCRIPT
    from acme.integrations.model_providers.types import ProviderName, StopReason, Usage

    reply = ModelReply(
        blocks=(TextBlock(text=ANSWER),),
        stop_reason=StopReason.END_TURN,
        usage=Usage(input=160, output=40),
        model="claude-sonnet-5-5",
    )
    path.write_bytes(SCRIPT.dump_json({ProviderName.ANTHROPIC: [reply]}))


async def record_evidence(slug: str, session_id: UUID) -> None:
    sys.path.insert(0, str(REPO / "om" / "tests"))
    from contracts.evidence_storage import make_record, make_validation

    from acme.om.evidence.types.provenance import Provenance
    from acme.om.evidence.types.record import RunOutcome
    from acme.services.api.container import AppContainer, boot
    from acme.services.api.main import command_request
    from acme.services.api.settings import ApiSettings

    settings = ApiSettings()
    boot(settings)
    settings.refuse_remote()
    container = AppContainer.build(settings)
    await container.start()
    try:
        org = await container.storage.get_tenancy_storage().read_org_by_slug(slug)
        if org is None:
            raise SystemExit(f"no org {slug}")
        owner = await container.managers.tenancy.member_context(
            command_request(settings), org.id, org.created_by
        )
        await container.managers.agent_sessions.get_session(owner, session_id)
        evidence = container.managers.evidence
        await evidence.record_run(owner, make_record(session_id, check="unit"))
        await evidence.record_run(
            owner,
            make_record(
                session_id, check="browser", outcome=RunOutcome.FAILED, provenance=Provenance.TWIN
            ),
        )
        validation, validated = make_validation(session_id, 1)
        await container.storage.get_evidence_storage().create_validation(
            owner.org_id, validation, validated
        )
    finally:
        await container.close()


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "script":
        write_script(Path(argv[1]))
        return 0
    if len(argv) == 3 and argv[0] == "evidence":
        asyncio.run(record_evidence(argv[1], UUID(argv[2])))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
