"""`acme-ops levers`: the operator's `read` token reads one org's levers
over the last days from `/v1/admin/orgs/<org>/levers`, and the reading is
printed as JSON, each lever by its kind, id, and version alone; a window of
no days is refused before any call."""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from acme.ops.main import levers_command

ORG = UUID("0199a4c0-0000-7000-8000-00000000000a")
SESSION = "0199a4c0-0000-7000-8000-0000000000c1"
READING = {
    "since": "2026-10-04T12:00:00Z",
    "until": "2026-10-11T12:00:00Z",
    "sessions": 5,
    "spun": 3,
    "complete": True,
    "standings": [
        {
            # A name the API should never answer, which the command never
            # prints: what it prints of a lever is its shape.
            "lever": {
                "kind": "agent_playbook",
                "id": "0199a4c0-0000-7000-8000-0000000000b1",
                "name": "flaky-deploys",
                "version": 2,
            },
            "sessions": 2,
            "spun": 2,
            "sessions_without": 3,
            "spun_without": 1,
            "lift": 2 / 3,
            "spun_sessions": [SESSION],
        }
    ],
}
asked: list[httpx.Request] = []


def operator_api(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer opt_read"
    asked.append(request)
    if request.url.path == f"/v1/admin/orgs/{ORG}/levers":
        return httpx.Response(200, json=READING)
    return httpx.Response(404, json={"error": {"code": "not_found", "message": "no"}})


def env_file(home: Path) -> None:
    file = home / ".config" / "acme" / "ops" / "staging.env"
    file.parent.mkdir(parents=True)
    file.write_text("ACME_API_URL=http://test\nACME_OPERATOR_TOKEN=opt_read\n")
    file.chmod(0o600)


async def test_levers_reads_the_window_with_the_read_token_and_prints_the_reading(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ACME_API_URL", raising=False)
    monkeypatch.delenv("ACME_OPERATOR_TOKEN", raising=False)
    asked.clear()
    code = await levers_command(
        argparse.Namespace(env="staging", org=ORG, days=7.0),
        transport=httpx.MockTransport(operator_api),
    )
    assert code == 0
    (request,) = asked
    since = datetime.fromisoformat(request.url.params["since"])
    until = datetime.fromisoformat(request.url.params["until"])
    assert until - since == timedelta(days=7)
    printed = json.loads(capsys.readouterr().out)
    (standing,) = printed["standings"]
    assert standing["lever"] == {
        "kind": "agent_playbook",
        "id": "0199a4c0-0000-7000-8000-0000000000b1",
        "version": 2,
    }
    assert standing["spun_sessions"] == [SESSION]


async def test_levers_refuses_a_window_of_no_days_before_any_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    asked.clear()
    code = await levers_command(
        argparse.Namespace(env="staging", org=ORG, days=0.0),
        transport=httpx.MockTransport(operator_api),
    )
    assert code == 2 and asked == []
    assert "--days" in capsys.readouterr().err
