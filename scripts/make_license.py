"""Issue licence keys. A developer tool: it needs the private signing key,
which is not in the repository.

  uv run python scripts/make_license.py --keygen
      Once: create the key pair and print the public key to paste into
      src/gametl/app/license.py (PUBLIC_KEY_HEX).
  uv run python scripts/make_license.py --name "Ada Lovelace" --email ada@example.com --machine ABCD-1234-EF56-7890
  uv run python scripts/make_license.py --name "..." --email "..." --machine "..." --expires 2027-12-31
      Print a key for a customer. The computer code is on their Licence page
      (and in `gametl-cli --license-status`); the key works on that computer
      only. Without --expires the key is perpetual.
  uv run python scripts/make_license.py --check GAMETL-...
      Read a key and verify it against the public key built into the app.

The private key lives in ~/Documents/gametl-license/license_private.pem
unless --key-file says otherwise. Keep a backup: without it no further keys
can be issued, and a new key pair means a new build for every customer.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from gametl.app.license import LicenseError, generate_keypair, machine_code, make_key, normalise_code, parse_key

DEFAULT_KEY_FILE = Path.home() / "Documents" / "gametl-license" / "license_private.pem"


def keygen(path: Path) -> int:
    if path.exists():
        print(f"{path} exists; refusing to overwrite the signing key")
        return 2
    pem, public_hex = generate_keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pem)
    print(f"private key written to {path}  (back it up, never commit it)")
    print(f'PUBLIC_KEY_HEX = "{public_hex}"')
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--keygen", action="store_true", help="create the key pair and print the public key")
    p.add_argument("--check", metavar="KEY", help="verify a key against the app's public key")
    p.add_argument("--name", help="licensee name as it should appear in the app")
    p.add_argument("--email")
    p.add_argument("--machine", help="the customer's computer code, from their Licence page")
    p.add_argument("--expires", help="YYYY-MM-DD; omit for a perpetual key")
    p.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    args = p.parse_args()

    if args.keygen:
        return keygen(args.key_file)
    if args.check:
        try:
            licence = parse_key(args.check, machine=_machine_of(args.check))
        except LicenseError as exc:
            print(f"invalid: {exc}")
            return 1
        until = licence.expires.isoformat() if licence.expires else "never"
        here = "this computer" if licence.machine == machine_code() else "another computer"
        print(f"valid: {licence.name} <{licence.email}>, issued {licence.issued}, expires {until}")
        print(f"       for computer {licence.machine} ({here})")
        return 0
    if not args.name or not args.email or not args.machine:
        p.error("--name, --email and --machine are required to issue a key (or use --keygen / --check)")
    if not args.key_file.exists():
        print(f"no private key at {args.key_file}; run --keygen first or pass --key-file")
        return 2
    expires = date.fromisoformat(args.expires) if args.expires else None
    key = make_key(args.key_file.read_bytes(), args.name, args.email, date.today(), args.machine, expires)
    print(key)
    return 0


def _machine_of(key: str) -> str | None:
    """The computer code a key names, read without verifying, so --check can
    report a key issued for another computer as valid rather than rejected."""
    import json

    from gametl.app.license import KEY_PREFIX, _b64decode

    try:
        body = key.strip()[len(KEY_PREFIX) :].partition(".")[0]
        return normalise_code(str(json.loads(_b64decode(body))["machine"]))
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
