"""Licence keys: signing, verification, trial counting and activation, with
a key pair made for the test (the app's real private key is not here)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gametl.app.config import ProfileStore
from gametl.app.credentials import MemorySecretStore
from gametl.app.license import (
    TRIAL_DAYS,
    LicenseError,
    activate,
    deactivate,
    license_status,
    make_key,
    parse_key,
)

TODAY = date(2026, 10, 23)


@pytest.fixture(scope="module")
def keypair() -> tuple[bytes, str]:
    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return pem, private.public_key().public_bytes_raw().hex()


def test_key_round_trip_and_tampering(keypair: tuple[bytes, str]) -> None:
    pem, public = keypair
    key = make_key(pem, "Ada Lovelace", "ada@example.com", TODAY, expires=date(2027, 1, 1), seats=2)
    assert key.startswith("GAMETL-")
    licence = parse_key(key, public)
    assert (licence.name, licence.email, licence.seats) == ("Ada Lovelace", "ada@example.com", 2)
    assert licence.issued == TODAY and licence.expires == date(2027, 1, 1)
    assert licence.valid_on(date(2027, 1, 1)) and not licence.valid_on(date(2027, 1, 2))

    perpetual = parse_key(make_key(pem, "Bob", "bob@example.com", TODAY), public)
    assert perpetual.expires is None and perpetual.valid_on(date(2099, 1, 1))

    body, _, signature = key[len("GAMETL-") :].partition(".")
    other_pem, _ = (Ed25519PrivateKey.generate(), None)
    forged = make_key(
        other_pem.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
        "Ada Lovelace",
        "ada@example.com",
        TODAY,
    )
    with pytest.raises(LicenseError):
        parse_key(forged, public)  # signed with someone else's key
    with pytest.raises(LicenseError):
        parse_key("GAMETL-" + body[:-2] + "AA." + signature, public)  # payload changed
    with pytest.raises(LicenseError):
        parse_key("not a key", public)
    with pytest.raises(LicenseError):
        parse_key("", public)


def test_trial_counts_from_first_start_and_survives_a_deleted_config(tmp_path: Path, keypair) -> None:
    _, public = keypair
    secrets = MemorySecretStore()
    store = ProfileStore(tmp_path)
    first = license_status(secrets, store, TODAY, public)
    assert first.licensed is False and first.trial_days_left == TRIAL_DAYS and first.may_run
    assert first.text == f"trial: {TRIAL_DAYS} days left"

    later = license_status(secrets, store, TODAY + timedelta(days=TRIAL_DAYS - 1), public)
    assert later.trial_days_left == 1 and later.text == "trial: 1 day left"

    over = license_status(secrets, store, TODAY + timedelta(days=TRIAL_DAYS), public)
    assert over.trial_days_left == 0 and over.may_run is False
    assert over.text == "trial over: a licence key is needed"

    # config.json gone: the secret store still remembers the first start.
    store.config_path.unlink()
    assert license_status(secrets, store, TODAY + timedelta(days=TRIAL_DAYS), public).may_run is False
    # the secret gone: config.json remembers it.
    secrets.delete("TRIAL_START")
    assert license_status(secrets, store, TODAY + timedelta(days=TRIAL_DAYS), public).may_run is False


def test_activation_and_expiry(tmp_path: Path, keypair: tuple[bytes, str]) -> None:
    pem, public = keypair
    secrets = MemorySecretStore()
    store = ProfileStore(tmp_path)
    assert license_status(secrets, store, TODAY, public).trial_days_left == TRIAL_DAYS  # first start recorded
    with pytest.raises(LicenseError):
        activate("GAMETL-garbage.more", secrets, public)
    assert secrets.get("LICENSE_KEY") is None

    key = make_key(pem, "Ada Lovelace", "ada@example.com", TODAY, expires=date(2026, 12, 31))
    assert activate(key, secrets, public).name == "Ada Lovelace"
    status = license_status(secrets, store, TODAY + timedelta(days=60), public)  # past the trial, inside the licence
    assert status.licensed and status.may_run
    assert status.text == "licensed to Ada Lovelace until 2026-12-31"

    expired = license_status(secrets, store, date(2027, 1, 1), public)  # trial long over too
    assert expired.licensed is False and expired.may_run is False
    assert expired.text.startswith("the licence for Ada Lovelace expired on 2026-12-31")

    deactivate(secrets)
    assert (
        license_status(secrets, store, TODAY + timedelta(days=1), public).text == f"trial: {TRIAL_DAYS - 1} days left"
    )
