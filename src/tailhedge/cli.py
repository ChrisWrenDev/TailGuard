"""TailHedge CLI entry point."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from tailhedge.persistence.engine import get_session_factory
from tailhedge.persistence.models import AppUser
from tailhedge.web.auth import hash_password

MIN_PASSWORD_LENGTH = 12


def create_owner(username: str) -> int:
    """Create the single owner account interactively."""
    password = getpass.getpass(f"Password for {username!r}: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: Passwords do not match.", file=sys.stderr)
        return 1
    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"Error: Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return 1

    session_factory = get_session_factory()
    with session_factory() as session:
        existing = session.scalar(select(AppUser).where(AppUser.username == username))
        if existing is not None:
            print(f"Error: User {username!r} already exists.", file=sys.stderr)
            return 1
        user = AppUser(
            username=username,
            password_hash=hash_password(password),
            role="OWNER",
        )
        session.add(user)
        session.commit()
        print(f"Owner account {username!r} created.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the TailHedge CLI."""
    parser = argparse.ArgumentParser(
        prog="tailhedge",
        description="TailHedge management CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    owner_parser = subparsers.add_parser(
        "create-owner", help="Create the single owner login account."
    )
    owner_parser.add_argument(
        "--username",
        default="owner",
        help="Owner username (default: owner)",
    )

    args = parser.parse_args(argv)

    if args.command == "create-owner":
        try:
            return create_owner(args.username)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
