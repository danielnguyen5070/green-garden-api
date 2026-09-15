"""CLI entrypoint: python -m app.cli create-admin"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from app.core.database import AsyncSessionLocal
from app.core.security import normalize_email
from app.services.auth_service import create_admin


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if not password:
        raise SystemExit("Password is required.")
    if password != confirm:
        raise SystemExit("Passwords do not match.")
    try:
        from app.core.security import validate_password_strength

        validate_password_strength(password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    return password


async def _create_admin(name: str, email: str, password: str) -> None:
    async with AsyncSessionLocal() as session:
        admin = await create_admin(
            session,
            name=name,
            email=email,
            password=password,
        )
    print(f"Created admin id={admin.id} email={admin.email}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Green Garden admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-admin", help="Create an admin user securely")
    create.add_argument("--name", help="Admin display name")
    create.add_argument("--email", help="Admin email (stored lowercase)")
    create.add_argument(
        "--password",
        help="Admin password (prefer interactive prompt; avoid shell history)",
    )

    args = parser.parse_args(argv)

    if args.command == "create-admin":
        name = (args.name or input("Name: ")).strip()
        email = normalize_email(args.email or input("Email: "))
        if not name or not email:
            raise SystemExit("Name and email are required.")
        password = args.password if args.password is not None else _prompt_password()
        try:
            asyncio.run(_create_admin(name, email, password))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
