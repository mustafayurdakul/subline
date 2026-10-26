"""Issue licence keys. A developer tool: it needs the private signing key,
which is not in the repository.

  uv run python scripts/make_license.py --keygen
      Once: create the key pair and print the public key to paste into
      src/gametl/app/license.py (PUBLIC_KEY_HEX).
  uv run python scripts/make_license.py --name "Ada Lovelace" --email ada@example.com
  uv run python scripts/make_license.py --name "..." --email "..." --expires 2027-12-31 --seats 2
      Print a key for a customer. Without --expires the key is perpetual.
  uv run python scripts/make_license.py --check GAMETL-...
      Verify a key against the public key built into the app.

The private key lives in ~/Documents/gametl-license/license_private.pem
unless --key-file says otherwise. Keep a backup: without it no further keys
can be issued, and a new key pair means a new build for every customer.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from gametl.app.license import LicenseError, generate_keypair, make_key, parse_key

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
    p.add_argument("--expires", help="YYYY-MM-DD; omit for a perpetual key")
    p.add_argument("--seats", type=int, default=1)
    p.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    args = p.parse_args()

    if args.keygen:
        return keygen(args.key_file)
    if args.check:
        try:
            licence = parse_key(args.check)
        except LicenseError as exc:
            print(f"invalid: {exc}")
            return 1
        until = licence.expires.isoformat() if licence.expires else "never"
        print(f"valid: {licence.name} <{licence.email}>, issued {licence.issued}")
        print(f"       expires {until}, seats {licence.seats}")
        return 0
    if not args.name or not args.email:
        p.error("--name and --email are required to issue a key (or use --keygen / --check)")
    if not args.key_file.exists():
        print(f"no private key at {args.key_file}; run --keygen first or pass --key-file")
        return 2
    expires = date.fromisoformat(args.expires) if args.expires else None
    key = make_key(args.key_file.read_bytes(), args.name, args.email, date.today(), expires, args.seats)
    print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
