"""Licence keys: signing, verification, the computer binding, the trial's
used-time accounting and activation, with a key pair made for the test
(the app's real private key is not here)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from gametl.app.config import ProfileStore
from gametl.app.credentials import MemorySecretStore
from gametl.app.license import (
    TRIAL_SECONDS,
    LicenseError,
    activate,
    deactivate,
    generate_keypair,
    license_status,
    machine_code,
    make_key,
    normalise_code,
    parse_key,
    record_trial_use,
    trial_text,
)

TODAY = date(2026, 10, 23)
HERE = machine_code("test-machine")
ELSEWHERE = machine_code("another-machine")


def test_computer_codes_are_stable_and_readable() -> None:
    assert HERE == machine_code("test-machine") != ELSEWHERE
    assert len(HERE) == 19 and HERE.count("-") == 3 and HERE.upper() == HERE
    assert normalise_code(HERE.lower().replace("-", " ")) == HERE  # as a customer may type it
    assert len(machine_code()) == 19  # this computer has one too (machine id or host name off Windows)


def test_key_round_trip_tampering_and_the_computer_binding(keypair: tuple[bytes, str]) -> None:
    pem, public = keypair
    key = make_key(pem, "Ada Lovelace", "ada@example.com", TODAY, HERE, expires=date(2027, 1, 1))
    assert key.startswith("GAMETL-")
    licence = parse_key(key, public, machine=HERE)
    assert (licence.name, licence.email, licence.machine) == ("Ada Lovelace", "ada@example.com", HERE)
    assert licence.issued == TODAY and licence.expires == date(2027, 1, 1)
    assert licence.valid_on(date(2027, 1, 1)) and not licence.valid_on(date(2027, 1, 2))

    perpetual = parse_key(make_key(pem, "Bob", "bob@example.com", TODAY, HERE), public, machine=HERE)
    assert perpetual.expires is None and perpetual.valid_on(date(2099, 1, 1))

    with pytest.raises(LicenseError, match="another computer"):
        parse_key(key, public, machine=ELSEWHERE)  # a shared key is no use elsewhere

    body, _, signature = key[len("GAMETL-") :].partition(".")
    other_pem, _ = generate_keypair()
    forged = make_key(other_pem, "Ada Lovelace", "ada@example.com", TODAY, HERE)
    with pytest.raises(LicenseError, match="was not issued for Subline"):
        parse_key(forged, public, machine=HERE)  # signed with someone else's key
    with pytest.raises(LicenseError):
        parse_key("GAMETL-" + body[:-2] + "AA." + signature, public, machine=HERE)  # payload changed
    with pytest.raises(LicenseError, match="not a Subline licence key"):  # the product's name, not the package's
        parse_key("not a key", public, machine=HERE)
    with pytest.raises(LicenseError):
        parse_key("", public, machine=HERE)


def test_trial_text() -> None:
    assert trial_text(TRIAL_SECONDS) == "trial: 3 h left"
    assert trial_text(2 * 3600 + 40 * 60) == "trial: 2 h 40 min left"
    assert trial_text(3570) == "trial: 1 h left"  # 59.5 minutes rounds up to the hour
    assert trial_text(12 * 60) == "trial: 12 min left"
    assert trial_text(1) == "trial: 1 min left"
    assert trial_text(0) == "trial over: a licence key is needed"


def test_trial_counts_translation_time_and_survives_deleted_copies(tmp_path: Path, keypair) -> None:
    _, public = keypair
    secrets = MemorySecretStore()
    store = ProfileStore(tmp_path)
    first = license_status(secrets, store, TODAY, public, machine=HERE)
    assert first.licensed is False and first.trial_seconds_left == TRIAL_SECONDS and first.may_run
    assert first.text == "trial: 3 h left"

    assert record_trial_use(secrets, store, 20 * 60) == TRIAL_SECONDS - 20 * 60
    assert license_status(secrets, store, TODAY, public, machine=HERE).text == "trial: 2 h 40 min left"
    assert secrets.get("TRIAL_USED") == "1200" and store.load_config()["trial_used"] == 1200

    # config.json gone: the secret store still remembers; the secret gone: config.json does.
    store.config_path.unlink()
    assert license_status(secrets, store, TODAY, public, machine=HERE).trial_seconds_left == TRIAL_SECONDS - 1200
    assert store.load_config()["trial_used"] == 1200  # written back
    secrets.delete("TRIAL_USED")
    assert license_status(secrets, store, TODAY, public, machine=HERE).trial_seconds_left == TRIAL_SECONDS - 1200
    assert secrets.get("TRIAL_USED") == "1200"
    # A copy wound back by hand does not help: the largest wins.
    secrets.set("TRIAL_USED", "5")
    assert license_status(secrets, store, TODAY, public, machine=HERE).trial_seconds_left == TRIAL_SECONDS - 1200
    # The registry copy (in memory here, HKEY_CURRENT_USER on Windows) is the third: alone, it still counts.
    secrets.delete("TRIAL_USED")
    store.config_path.unlink()
    assert license_status(secrets, store, TODAY, public, machine=HERE).trial_seconds_left == TRIAL_SECONDS - 1200

    assert record_trial_use(secrets, store, TRIAL_SECONDS) == 0
    over = license_status(secrets, store, TODAY, public, machine=HERE)
    assert over.trial_seconds_left == 0 and over.may_run is False
    assert over.text == "trial over: a licence key is needed"


def test_activation_and_expiry(tmp_path: Path, keypair: tuple[bytes, str]) -> None:
    pem, public = keypair
    secrets = MemorySecretStore()
    store = ProfileStore(tmp_path)
    with pytest.raises(LicenseError):
        activate("GAMETL-garbage.more", secrets, public, machine=HERE)
    with pytest.raises(LicenseError, match="another computer"):
        activate(make_key(pem, "Eve", "eve@example.com", TODAY, ELSEWHERE), secrets, public, machine=HERE)
    assert secrets.get("LICENSE_KEY") is None

    key = make_key(pem, "Ada Lovelace", "ada@example.com", TODAY, HERE, expires=date(2026, 12, 31))
    assert activate(key, secrets, public, machine=HERE).name == "Ada Lovelace"
    record_trial_use(secrets, store, TRIAL_SECONDS)  # the trial is long used up: the key carries the app
    status = license_status(secrets, store, TODAY, public, machine=HERE)
    assert status.licensed and status.may_run
    assert status.text == "licensed to Ada Lovelace until 2026-12-31"

    expired = license_status(secrets, store, date(2027, 1, 1), public, machine=HERE)
    assert expired.licensed is False and expired.may_run is False
    assert expired.text.startswith("the licence for Ada Lovelace expired on 2026-12-31")

    deactivate(secrets)
    assert license_status(secrets, store, TODAY, public, machine=HERE).text == "trial over: a licence key is needed"
