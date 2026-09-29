"""Seed demo reviewers for NOCTRA.
Creates two reviewers (one 'reviewer' role, one 'viewer' role) with hashed tokens,
and prints their raw tokens once to stdout.
"""
from __future__ import annotations

import hashlib
import secrets
import sys
from pathlib import Path

# Add backend directory to sys.path so we can import app modules
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402
from app.db import init_schema, get_conn  # noqa: E402


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def seed_demo_reviewers() -> dict[str, str]:
    conn = get_conn()
    init_schema(conn)

    demo_accounts = [
        {"name": "Lead Reviewer", "role": "reviewer"},
        {"name": "Safety Viewer", "role": "viewer"},
    ]

    tokens = {}
    for acc in demo_accounts:
        token = f"noctra-rev-{acc['role']}-{secrets.token_hex(16)}"
        token_h = hash_token(token)

        # Deactivate previous account with the same name if exists, then insert
        db.execute("DELETE FROM reviewers WHERE name = ?", (acc["name"],))
        db.execute(
            "INSERT INTO reviewers (name, role, token_hash, active) VALUES (?, ?, ?, 1)",
            (acc["name"], acc["role"], token_h),
        )
        tokens[acc["name"]] = (acc["role"], token)

    return tokens


def main():
    print("=" * 60)
    print(" NOCTRA Demo Reviewer Accounts Seeding")
    print("=" * 60)
    tokens = seed_demo_reviewers()
    for name, (role, token) in tokens.items():
        print(f"\nAccount: {name}")
        print(f"Role:    {role}")
        print(f"Token:   {token}")
        print(f"Header:  Authorization: Bearer {token}")

    print("\n" + "=" * 60)
    print("IMPORTANT: Save these tokens now. Only SHA-256 hashes are")
    print("stored in the database; tokens cannot be recovered later.")
    print("=" * 60)


if __name__ == "__main__":
    main()
