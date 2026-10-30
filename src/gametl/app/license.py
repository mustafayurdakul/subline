"""Licence keys and the trial.

A key is the licensee's details, including the code of the computer it is
for, signed with Ed25519. The app verifies the signature offline with the
public key below, so no server is involved; keys are issued with
`scripts/make_license.py` and the private key, which stays with the
developer and is not in the repository. A key works only on the computer
whose code it names (the Licence page shows the code to send when buying).

Without a key the app runs for a trial of `TRIAL_SECONDS` of translation:
time while a session runs, not time since the first start. The used time
is kept in three places (the secret store, config.json and, on Windows,
the registry under HKEY_CURRENT_USER\\Software\\Subline); the largest copy
wins and the others are brought up to it, so deleting one of them does not
hand out a new trial. None of this stops a determined person with a
debugger: it keeps honest users honest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import APP_NAME
from .config import ProfileStore
from .credentials import SecretStore

PUBLIC_KEY_HEX = "964cce0741ce08885e388fb75828bf72d37da05cc6c03868a97d1f637edcfafa"
TRIAL_SECONDS = 3 * 60 * 60  # three hours of translation
KEY_PREFIX = "GAMETL-"  # the key format's own name; users see APP_NAME
LICENSE_SECRET = "LICENSE_KEY"  # the key, in the secret store
TRIAL_SECRET = "TRIAL_USED"  # seconds of trial used, in the secret store (and config.json and the registry)
TRIAL_CONFIG_KEY = "trial_used"
REGISTRY_KEY = r"Software\Subline"
REGISTRY_VALUE = "trial"
PURCHASE_URL = ""  # shown in the settings window when set
_SIGNED_PREFIX = b"gametl-license-v2:"


class LicenseError(ValueError):
    """The text is not a valid licence key for this app on this computer."""


# -- the computer ----------------------------------------------------------------


def machine_code(seed: str | None = None) -> str:
    """This computer's code, as shown on the Licence page and named in a
    key: a hash of Windows' machine GUID (elsewhere: the machine id or the
    host name), as four groups of four, like ABCD-1234-EF56-7890. `seed`
    stands in for the GUID in tests."""
    if seed is None:
        seed = _machine_seed()
    digest = hashlib.sha256(b"subline-machine:" + seed.encode("utf-8")).hexdigest()[:16].upper()
    return "-".join(digest[i : i + 4] for i in range(0, 16, 4))


def _machine_seed() -> str:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as key:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(guid)
    except (ImportError, AttributeError, OSError):  # not Windows (a stub winreg in tests), or no such value
        pass
    machine_id = Path("/etc/machine-id")
    if machine_id.exists():
        return machine_id.read_text(encoding="utf-8").strip()
    return platform.node()


# -- keys --------------------------------------------------------------------------


@dataclass(frozen=True)
class License:
    name: str
    email: str
    issued: date
    expires: date | None  # None: perpetual
    machine: str  # the computer code the key was issued for

    def valid_on(self, day: date) -> bool:
        return self.expires is None or day <= self.expires


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_keypair() -> tuple[bytes, str]:
    """A fresh Ed25519 signing key as (private PEM, public key hex): the
    PEM for `make_key`, the hex for PUBLIC_KEY_HEX (developer side)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return pem, private.public_key().public_bytes_raw().hex()


def make_key(
    private_key_pem: bytes, name: str, email: str, issued: date, machine: str, expires: date | None = None
) -> str:
    """Sign the licensee's details and the computer code into a key (developer side)."""
    from cryptography.hazmat.primitives import serialization

    private = serialization.load_pem_private_key(private_key_pem, password=None)
    payload = {
        "name": name,
        "email": email,
        "issued": issued.isoformat(),
        "expires": expires.isoformat() if expires else None,
        "machine": normalise_code(machine),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = private.sign(_SIGNED_PREFIX + body)  # type: ignore[union-attr]
    return KEY_PREFIX + _b64encode(body) + "." + _b64encode(signature)


def normalise_code(code: str) -> str:
    """A computer code as typed (spaces, lower case, missing dashes) in its canonical form."""
    digits = "".join(c for c in code.upper() if c.isalnum())
    return "-".join(digits[i : i + 4] for i in range(0, len(digits), 4))


def parse_key(key: str, public_key_hex: str | None = None, machine: str | None = None) -> License:
    """The licence a key carries, once its signature checks out and it names
    this computer (`machine` overrides the code looked up, for tests).
    Raises LicenseError for anything else."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = (key or "").strip()
    if not key.startswith(KEY_PREFIX) or "." not in key:
        raise LicenseError(f"not a {APP_NAME} licence key")
    body_text, _, signature_text = key[len(KEY_PREFIX) :].partition(".")
    try:
        body, signature = _b64decode(body_text), _b64decode(signature_text)
        public = bytes.fromhex(public_key_hex or PUBLIC_KEY_HEX)
        Ed25519PublicKey.from_public_bytes(public).verify(signature, _SIGNED_PREFIX + body)
        payload = json.loads(body)
        licence = License(
            name=str(payload["name"]),
            email=str(payload["email"]),
            issued=date.fromisoformat(payload["issued"]),
            expires=date.fromisoformat(payload["expires"]) if payload.get("expires") else None,
            machine=normalise_code(str(payload["machine"])),
        )
    except InvalidSignature:
        raise LicenseError(
            f"the signature does not match: the key was altered or was not issued for {APP_NAME}"
        ) from None
    except (ValueError, KeyError, TypeError) as exc:
        raise LicenseError(f"malformed licence key: {exc}") from exc
    here = normalise_code(machine) if machine else machine_code()
    if licence.machine != here:
        raise LicenseError(f"this key was issued for another computer (this one's code is {here})")
    return licence


# -- the trial ---------------------------------------------------------------------


def _registry_get() -> int | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE)
            return _as_seconds(value)
    except (ImportError, AttributeError, OSError):
        return None


def _registry_set(seconds: int) -> None:
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            winreg.SetValueEx(key, REGISTRY_VALUE, 0, winreg.REG_DWORD, int(seconds))
    except (ImportError, AttributeError, OSError):
        pass


def _as_seconds(value: object) -> int | None:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def trial_used(secrets: SecretStore, store: ProfileStore) -> int:
    """Seconds of the trial used so far: the largest of the copies kept,
    with the others brought up to it."""
    config = store.load_config()
    copies = [_as_seconds(secrets.get(TRIAL_SECRET)), _as_seconds(config.get(TRIAL_CONFIG_KEY)), _registry_get()]
    used = max((c for c in copies if c is not None), default=0)
    _write_trial(secrets, store, config, used)
    return used


def _write_trial(secrets: SecretStore, store: ProfileStore, config: dict, used: int) -> None:
    if _as_seconds(secrets.get(TRIAL_SECRET)) != used:
        secrets.set(TRIAL_SECRET, str(used))
    if _as_seconds(config.get(TRIAL_CONFIG_KEY)) != used:
        config[TRIAL_CONFIG_KEY] = used
        store.save_config(config)
    if _registry_get() != used:
        _registry_set(used)


def record_trial_use(secrets: SecretStore, store: ProfileStore, seconds: float) -> int:
    """Add `seconds` of translation to the trial; returns the seconds left."""
    used = trial_used(secrets, store) + max(0, int(seconds))
    _write_trial(secrets, store, store.load_config(), used)
    return max(0, TRIAL_SECONDS - used)


def trial_text(seconds_left: int) -> str:
    """One line: 'trial: 2 h 40 min left', 'trial: 12 min left', or over."""
    if seconds_left <= 0:
        return "trial over: a licence key is needed"
    minutes = -(-seconds_left // 60)  # rounded up: a minute left is still a minute
    hours, minutes = divmod(minutes, 60)
    parts = ([f"{hours} h"] if hours else []) + ([f"{minutes} min"] if minutes or not hours else [])
    return f"trial: {' '.join(parts)} left"


# -- status ------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseStatus:
    licensed: bool
    text: str  # one line for the settings window and the tray
    license: License | None = None
    trial_seconds_left: int | None = None  # None when licensed

    @property
    def may_run(self) -> bool:
        return self.licensed or (self.trial_seconds_left or 0) > 0


def license_status(
    secrets: SecretStore,
    store: ProfileStore,
    today: date | None = None,
    public_key_hex: str | None = None,
    machine: str | None = None,
) -> LicenseStatus:
    """Licensed, in the trial, or neither; `text` says which in one line."""
    today = today or date.today()
    problem = None
    key = secrets.get(LICENSE_SECRET)
    if key:
        try:
            licence = parse_key(key, public_key_hex, machine)
        except LicenseError as exc:
            problem = f"the stored licence key was rejected ({exc})"
        else:
            if licence.valid_on(today):
                until = f" until {licence.expires.isoformat()}" if licence.expires else ""
                return LicenseStatus(True, f"licensed to {licence.name}{until}", licence)
            problem = f"the licence for {licence.name} expired on {licence.expires.isoformat()}"  # type: ignore[union-attr]
    left = max(0, TRIAL_SECONDS - trial_used(secrets, store))
    text = trial_text(left)
    if problem:
        text = f"{problem}; {text}"
    return LicenseStatus(False, text, None, left)


def activate(key: str, secrets: SecretStore, public_key_hex: str | None = None, machine: str | None = None) -> License:
    """Check a key and keep it. Raises LicenseError when it does not verify
    or names another computer."""
    licence = parse_key(key, public_key_hex, machine)
    secrets.set(LICENSE_SECRET, key.strip())
    return licence


def deactivate(secrets: SecretStore) -> None:
    secrets.delete(LICENSE_SECRET)
