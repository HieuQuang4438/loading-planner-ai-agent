"""Accounts of the service, by command line (docs/product/architecture.md §5, §9): there is no sign-up page.

    python -m src.web.users seed | add NAME | disable NAME | passwd NAME | list

The file is `PLANNER_DB` (default `/data/app.db`). Passwords never come from arguments: `seed` reads
`PLANNER_ADMIN_NAME` / `PLANNER_ADMIN_PASSWORD`; `add` and `passwd` read `PLANNER_NEW_PASSWORD` or ask twice (no echo)."""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

from src.web.auth import hash_password, stamp
from src.web.db import connect, migrate

NAME_RE = re.compile(r"[a-z0-9_-]+")
MIN_PASSWORD = 12


class UserError(Exception):
    """A request the command cannot do; the message goes to stderr."""


def check_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise UserError("tên chỉ gồm chữ thường, số, '-' và '_'")


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise UserError(f"mật khẩu ít nhất {MIN_PASSWORD} ký tự")


def add_user(conn: sqlite3.Connection, name: str, password: str) -> None:
    check_name(name)
    check_password(password)
    try:
        conn.execute("INSERT INTO users (name, pw_hash, created_at) VALUES (?, ?, ?)",
                     (name, hash_password(password), stamp(datetime.now(timezone.utc))))
    except sqlite3.IntegrityError:
        raise UserError(f"đã có user {name!r}") from None


def _user_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise UserError(f"không có user {name!r}")
    return row["id"]


def seed(conn: sqlite3.Connection, name: str, password: str) -> bool:
    """Create the first admin; False (nothing changed) when the user exists."""
    if conn.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone():
        return False
    add_user(conn, name, password)
    return True


def disable_user(conn: sqlite3.Connection, name: str) -> None:
    uid = _user_id(conn, name)
    conn.execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))


def set_password(conn: sqlite3.Connection, name: str, password: str) -> None:
    check_password(password)
    uid = _user_id(conn, name)
    conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (hash_password(password), uid))
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM login_failures WHERE name = ?", (name,))


def _ask_password() -> str:
    env = os.environ.get("PLANNER_NEW_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Mật khẩu: ")
    if getpass.getpass("Nhập lại: ") != first:
        raise UserError("hai lần nhập không khớp")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.web.users", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="create the admin from PLANNER_ADMIN_NAME / PLANNER_ADMIN_PASSWORD if absent")
    for cmd in ("add", "disable", "passwd"):
        sub.add_parser(cmd).add_argument("name")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    conn = connect(os.environ.get("PLANNER_DB") or "/data/app.db")
    try:
        migrate(conn)
        if args.cmd == "seed":
            name, password = os.environ.get("PLANNER_ADMIN_NAME", ""), os.environ.get("PLANNER_ADMIN_PASSWORD", "")
            if not name or not password:
                raise UserError("cần PLANNER_ADMIN_NAME và PLANNER_ADMIN_PASSWORD")
            print(f"đã tạo admin {name!r}" if seed(conn, name, password) else f"admin {name!r} đã có, không đổi")
        elif args.cmd == "add":
            add_user(conn, args.name, _ask_password())
            print(f"đã tạo user {args.name!r}")
        elif args.cmd == "passwd":
            set_password(conn, args.name, _ask_password())
            print(f"đã đổi mật khẩu của {args.name!r}; phiên cũ bị xóa")
        elif args.cmd == "disable":
            disable_user(conn, args.name)
            print(f"đã khóa user {args.name!r}; phiên bị xóa")
        else:
            for row in conn.execute("SELECT name, active, created_at FROM users ORDER BY id"):
                print(f"{row['name']}\t{'active' if row['active'] else 'disabled'}\t{row['created_at']}")
    except UserError as exc:
        print(f"lỗi: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
