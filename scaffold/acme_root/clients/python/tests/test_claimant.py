"""The claimant kit's parts that need no platform: the credential file,
written owner-only and whole or not at all; the journal's entries and
where each waits; the lease clock; and the credential kept live through a
long work, over a stand-in for the platform. The kit against the live app
is `services/api/tests/test_claimant_kit_api.py`."""

import asyncio
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from acme.client.claimant.claimant import Claimant
from acme.client.claimant.credential import (
    BadSetting,
    Credential,
    load_credential,
    save_credential,
)
from acme.client.claimant.journal import Entry, Journal
from acme.client.claimant.lease import LeaseClock
from acme.client.claimant.settings import ClaimantSettings, claimant_env
from acme.client.client import ApiClient
from acme.client.leases import MIN_RENEW_SECONDS
from acme.client.leases import LeaseClock as HoldClock
from acme.client.types import ClaimantWorkView, ReportOutcome

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def a_credential(token: str = "scn_first") -> Credential:
    return Credential(
        api_url="https://api.acme.example",
        token=token,
        credential_id=str(uuid4()),
        claimant_id=str(uuid4()),
        pool_id=str(uuid4()),
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def test_the_credential_is_written_owner_only_and_whole_or_not_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "home" / "credential.json"
    first = a_credential()
    before = os.umask(0)
    try:
        save_credential(path, first)
    finally:
        os.umask(before)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert load_credential(path) == first

    # A write that fails before its move leaves the one before, whole.
    held = path.read_text()

    def refused(source: object, target: object) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(os, "replace", refused)
    with pytest.raises(BadSetting):
        save_credential(path, a_credential("scn_second"))
    assert path.read_text() == held
    leftover = path.with_name(".credential.json.tmp")
    assert stat.S_IMODE(leftover.stat().st_mode) == 0o600


def test_a_credential_is_due_at_half_its_life_and_a_hosts_file_still_loads(
    tmp_path: Path,
) -> None:
    held = a_credential()
    assert not held.due(NOW + timedelta(minutes=29))
    assert held.due(NOW + timedelta(minutes=30))
    assert not held.ended(NOW + timedelta(minutes=59)) and held.ended(NOW + timedelta(hours=1))
    path = tmp_path / "credential.json"
    save_credential(path, held)
    raw = json.loads(path.read_text())
    raw["host_id"] = raw.pop("claimant_id")
    path.write_text(json.dumps(raw))
    assert load_credential(path) == held
    for broken in ("", "[]", '"host_id"', '{"token": "scn_x"}'):
        path.write_text(broken)
        assert load_credential(path) is None


def test_a_kinds_settings_are_read_under_its_prefix(tmp_path: Path) -> None:
    env = {
        "ACME_API_URL": "https://api.acme.example/",
        "ACME_DOC_SCANNER_HOME": str(tmp_path),
        "ACME_DOC_SCANNER_NAME": "scanner-1",
        "ACME_ENROLLMENT_TOKEN": "dsc_once",
    }
    settings = ClaimantSettings(**claimant_env("ACME", "doc_scanner", env))
    assert (settings.api_url, settings.home, settings.name) == (
        "https://api.acme.example",
        tmp_path,
        "scanner-1",
    )
    assert settings.enrollment_token == "dsc_once"
    assert settings.credential_path == tmp_path / "credential.json"
    assert claimant_env("ACME", "doc_scanner", {})["home"].name == "acme-doc-scanner"


def test_the_journal_keeps_a_report_until_it_is_sent_and_sets_aside_what_waits(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "journal")
    assert journal.pending() == []
    first, second = (
        Entry(str(item), str(item), {"claim_token": str(uuid4()), "outcome": "done"})
        for item in (uuid4(), uuid4())
    )
    journal.keep(first)
    journal.keep(second)
    assert journal.pending() == [first, second]
    assert journal.find(first.key) == first
    journal.sent(first.key)
    assert journal.pending() == [second]

    # Its claim lapsed: it waits for a later claim of its item, outside the
    # flush, and lands under that claim's token.
    journal.lapse(second.key)
    assert journal.pending() == []
    lapsed = journal.lapsed(UUID(second.item_id))
    assert lapsed == second
    token = uuid4()
    again = second.under(UUID(second.item_id), token)
    assert again.body["claim_token"] == str(token) and again.body["outcome"] == "done"
    journal.keep(again)
    assert journal.pending() == [again] and journal.lapsed(UUID(second.item_id)) is None

    # Refused for its shape: kept for a person, and never sent again.
    journal.set_aside(again.key)
    assert journal.pending() == [] and journal.lapsed(UUID(second.item_id)) is None
    assert (tmp_path / "journal" / f"{again.key}.refused.json").exists()

    # A key is an id: none names a path outside the journal.
    with pytest.raises(ValueError):
        journal.keep(Entry("../credential", second.item_id, {}))


def test_the_lease_clock_renews_at_half_the_shorter_and_asks_again_sooner_unanswered() -> None:
    """The hold is the client's lease clock, and the claim beside it
    brings the renewal forward when it is the shorter of the two."""
    lease = LeaseClock.started(100.0, 300.0, 60.0)
    assert isinstance(lease.hold, HoldClock)
    assert (lease.deadline, lease.claim_deadline, lease.renew_at) == (400.0, 160.0, 130.0)
    lease.unanswered(130.0)
    assert lease.renew_at == 145.0 and lease.deadline == 400.0
    lease.unanswered(145.0, wait=30.0)
    assert lease.renew_at == 145.0 + 15.0 - MIN_RENEW_SECONDS
    lease.renewed(150.0, 300.0, 60.0)
    assert (lease.deadline, lease.renew_at) == (450.0, 180.0)
    # Past the claim, the hold alone times the next ask.
    lease.unanswered(215.0)
    assert lease.renew_at == 215.0 + (450.0 - 215.0) / 2
    # A hold shorter than the claim times the renewal by itself.
    short = LeaseClock.started(100.0, 60.0, 300.0)
    assert (short.deadline, short.claim_deadline, short.renew_at) == (160.0, 400.0, 130.0)
    short.unanswered(130.0)
    assert short.renew_at == 145.0
    alone = LeaseClock.started(0.0, 1.0)
    assert alone.renew_at == MIN_RENEW_SECONDS and not alone.out(0.5) and alone.out(1.0)
    alone.refused = True
    assert alone.out(0.0) and alone.hold.lost(0.0)
    ended = LeaseClock.started(0.0, 60.0)
    ended.ended = "revoked"
    assert ended.out(0.0) and not ended.hold.lost(0.0)


async def test_a_work_longer_than_the_rotation_keeps_its_credential_live(tmp_path: Path) -> None:
    """A work that runs past half the credential's life, and past its end,
    over a clock the test moves and a beat of a few milliseconds: the
    credential is rotated while the work runs and kept once it ends, and
    its report is recorded. The stand-in for the platform refuses a
    credential once it ends, as the platform does."""
    clock = [NOW]
    first = a_credential()
    settings = ClaimantSettings(
        api_url=first.api_url,
        home=tmp_path,
        name="scanner-1",
        enrollment_token=None,
        beat_seconds=0.005,
    )
    save_credential(settings.credential_path, first)
    ends = {first.token: first.expires_at}
    reports: list[dict[str, Any]] = []
    rotated = asyncio.Event()
    item = ClaimantWorkView.model_validate(
        {
            "attempts": 1,
            "claim_token": str(uuid4()),
            "id": str(uuid4()),
            "kind": "scanner",
            "lease_expires_at": None,
            "org_id": str(uuid4()),
            "payload": {},
            "status": "claimed",
            "target_id": str(uuid4()),
        }
    )

    async def platform(request: httpx.Request) -> httpx.Response:
        bearer = request.headers["Authorization"].removeprefix("Bearer ")
        if bearer not in ends or clock[0] >= ends[bearer]:
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "ended"}})
        if request.url.path == "/v1/claimants/me/credentials":
            token = f"scn_{len(ends) + 1}"
            ends[token] = clock[0] + timedelta(hours=1)
            rotated.set()
            await asyncio.sleep(0.01)  # its answer is still on the wire as the work ends
            return httpx.Response(
                201,
                json={
                    "token": token,
                    "credential_id": str(uuid4()),
                    "claimant_id": first.claimant_id,
                    "pool_id": first.pool_id,
                    "kind": "scanner",
                    "expires_at": ends[token].isoformat(),
                },
            )
        assert request.url.path == f"/v1/claimants/me/items/{item.id}/report"
        reports.append(json.loads(request.content))
        return httpx.Response(200, json=item.model_dump(mode="json"))

    def client_for(token: str | None) -> ApiClient:
        return ApiClient(
            settings.api_url,
            app="api",
            app_version="scanner@0.1.0",
            token=token,
            transport=httpx.MockTransport(platform),
        )

    claimant = Claimant(settings, client_for, now=lambda: clock[0])
    await claimant.start()  # picks up the credential it holds
    assert claimant.enrollment.credential == first

    async def work() -> None:
        clock[0] = NOW + timedelta(minutes=31)  # past half its life: due
        async with asyncio.timeout(1):
            await rotated.wait()  # rotated while the work runs
        clock[0] = NOW + timedelta(minutes=61)  # the first credential has ended

    async with claimant.keeping_alive():
        await work()

    held = claimant.enrollment.credential
    assert held.token == "scn_2" and not claimant.enrollment.refused
    assert load_credential(settings.credential_path) == held
    assert await claimant.report(item, ReportOutcome.done)
    assert reports == [{"claim_token": str(item.claim_token), "outcome": "done"}]
    assert claimant.journal.pending() == []
