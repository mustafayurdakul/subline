"""Licence keys.

A key is the licensee's details signed with Ed25519. The app verifies the
signature offline with the public key below, so no server is involved;
keys are issued with `scripts/make_license.py` and the private key, which
stays with the developer and is not in the repository. Without a key the
app runs for a `TRIAL_DAYS` trial counted from its first start.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date

from .config import ProfileStore
from .credentials import SecretStore

PUBLIC_KEY_HEX = "964cce0741ce08885e388fb75828bf72d37da05cc6c03868a97d1f637edcfafa"
TRIAL_DAYS = 14
KEY_PREFIX = "GAMETL-"
LICENSE_SECRET = "LICENSE_KEY"  # the key, in the secret store
TRIAL_SECRET = "TRIAL_START"  # first-start date, in the secret store (and config.json)
PURCHASE_URL = ""  # shown in the settings window when set
_SIGNED_PREFIX = b"gametl-license-v1:"


class LicenseError(ValueError):
    """The text is not a valid gametl licence key."""


@dataclass(frozen=True)
class License:
    name: str
    email: str
    issued: date
    expires: date | None  # None: perpetual
    seats: int = 1

    def valid_on(self, day: date) -> bool:
        return self.expires is None or day <= self.expires


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_key(
    private_key_pem: bytes, name: str, email: str, issued: date, expires: date | None = None, seats: int = 1
) -> str:
    """Sign the licensee's details into a key (developer side)."""
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(private_key_pem, password=None)
    payload = {
        "name": name,
        "email": email,
        "issued": issued.isoformat(),
        "expires": expires.isoformat() if expires else None,
        "seats": seats,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = private.sign(_SIGNED_PREFIX + body)  # type: ignore[union-attr]
    return KEY_PREFIX + _b64encode(body) + "." + _b64encode(signature)


def parse_key(key: str, public_key_hex: str | None = None) -> License:
    """The licence a key carries, once its signature checks out. Raises
    LicenseError for anything else."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = (key or "").strip()
    if not key.startswith(KEY_PREFIX) or "." not in key:
        raise LicenseError("not a gametl licence key")
    body_text, _, signature_text = key[len(KEY_PREFIX) :].partition(".")
    try:
        body, signature = _b64decode(body_text), _b64decode(signature_text)
        public = bytes.fromhex(public_key_hex or PUBLIC_KEY_HEX)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, _SIGNED_PREFIX + body)
        payload = json.loads(body)
        return License(
            name=str(payload["name"]),
            email=str(payload["email"]),
            issued=date.fromisoformat(payload["issued"]),
            expires=date.fromisoformat(payload["expires"]) if payload.get("expires") else None,
            seats=int(payload.get("seats", 1)),
        )
    except InvalidSignature:
        raise LicenseError("the signature does not match: the key was altered or was not issued for gametl") from None
    except (ValueError, KeyError, TypeError) as exc:
        raise LicenseError(f"malformed licence key: {exc}") from exc


# -- status ------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseStatus:
    licensed: bool
    text: str  # one line for the settings window and the tray
    license: License | None = None
    trial_days_left: int | None = None  # None when licensed

    @property
    def may_run(self) -> bool:
        return self.licensed or (self.trial_days_left or 0) > 0


def trial_start(secrets: SecretStore, store: ProfileStore, today: date) -> date:
    """The first-start date. It is kept both in the secret store and in
    config.json; the earliest copy wins and a missing copy is restored, so
    deleting one of them does not restart the trial."""
    found: list[date] = []
    for text in (secrets.get(TRIAL_SECRET), store.load_config().get("trial_start")):
        try:
            if text:
                found.append(date.fromisoformat(str(text)))
        except ValueError:
            continue
    start = min(found) if found else today
    if secrets.get(TRIAL_SECRET) != start.isoformat():
        secrets.set(TRIAL_SECRET, start.isoformat())
    config = store.load_config()
    if config.get("trial_start") != start.isoformat():
        config["trial_start"] = start.isoformat()
        store.save_config(config)
    return start


def license_status(
    secrets: SecretStore, store: ProfileStore, today: date | None = None, public_key_hex: str | None = None
) -> LicenseStatus:
    """Licensed, in the trial, or neither; `text` says which in one line."""
    today = today or date.today()
    # Record the first start on every run, licensed or not, so a licence that
    # expires later does not hand out a fresh trial.
    start = trial_start(secrets, store, today)
    problem = None
    key = secrets.get(LICENSE_SECRET)
    if key:
        try:
            licence = parse_key(key, public_key_hex)
        except LicenseError as exc:
            problem = f"the stored licence key was rejected ({exc})"
        else:
            if licence.valid_on(today):
                until = f" until {licence.expires.isoformat()}" if licence.expires else ""
                return LicenseStatus(True, f"licensed to {licence.name}{until}", licence)
            problem = f"the licence for {licence.name} expired on {licence.expires.isoformat()}"  # type: ignore[union-attr]
    left = max(0, min(TRIAL_DAYS, TRIAL_DAYS - (today - start).days))
    days = "day" if left == 1 else "days"
    text = f"trial: {left} {days} left" if left > 0 else "trial over: a licence key is needed"
    if problem:
        text = f"{problem}; {text}"
    return LicenseStatus(False, text, None, left)


def activate(key: str, secrets: SecretStore, public_key_hex: str | None = None) -> License:
    """Check a key and keep it. Raises LicenseError when it does not verify."""
    licence = parse_key(key, public_key_hex)
    secrets.set(LICENSE_SECRET, key.strip())
    return licence


def deactivate(secrets: SecretStore) -> None:
    secrets.delete(LICENSE_SECRET)
