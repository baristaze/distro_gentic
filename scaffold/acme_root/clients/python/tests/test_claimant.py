"""The claimant kit's parts that need no platform: the credential file,
written owner-only and whole or not at all; the journal's entries and
where each waits; and the lease clock. The kit against the live app is
`services/api/tests/test_claimant_kit_api.py`."""

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from acme.client.claimant.credential import (
    BadSetting,
    Credential,
    load_credential,
    save_credential,
)
from acme.client.claimant.journal import Entry, Journal
from acme.client.claimant.lease import RETRY_FLOOR_SECONDS, LeaseClock
from acme.client.claimant.settings import ClaimantSettings, claimant_env

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
    lease = LeaseClock.started(100.0, 300.0, 60.0)
    assert (lease.deadline, lease.claim_deadline, lease.renew_at) == (400.0, 160.0, 130.0)
    lease.unanswered(130.0)
    assert lease.renew_at == 145.0 and lease.deadline == 400.0
    lease.unanswered(145.0, wait=30.0)
    assert lease.renew_at == 145.0 + 15.0 - RETRY_FLOOR_SECONDS
    lease.renewed(150.0, 300.0, 60.0)
    assert (lease.deadline, lease.renew_at) == (450.0, 180.0)
    alone = LeaseClock.started(0.0, 1.0)
    assert alone.renew_at == RETRY_FLOOR_SECONDS and not alone.out(0.5) and alone.out(1.0)
    alone.refused = True
    assert alone.out(0.0)
