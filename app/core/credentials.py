"""Operator helper: generate an API token and its SHA-256 hash for ``PULSEOPS_API_CREDENTIALS``.

    python -m app.core.credentials --generate        # prints a new token and its hash
    python -m app.core.credentials --hash            # reads a token from stdin and prints its hash

Only the hash belongs in configuration. The plaintext token is shown once; hand it to the client (for n8n:
``PULSEOPS_N8N_TOKEN``) and do not store it anywhere else.
"""

from __future__ import annotations

import argparse
import secrets
import sys

from app.core.security import hash_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.core.credentials")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true", help="generate a new random token and print token + hash")
    group.add_argument("--hash", action="store_true", help="read a token from stdin and print its SHA-256")
    args = parser.parse_args(argv)
    if args.generate:
        token = secrets.token_urlsafe(32)
        print(f"token:        {token}")
        print(f"token_sha256: {hash_token(token)}")
        return 0
    token = sys.stdin.readline().strip()
    if not token:
        print("no token supplied on stdin", file=sys.stderr)
        return 1
    print(hash_token(token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
