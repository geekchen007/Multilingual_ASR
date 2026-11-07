"""SQLite connections, account creation and schema initialization."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from flask import Flask
from werkzeug.security import generate_password_hash


@contextmanager
def database(app: Flask) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on error, and always close the connection."""
    connection = sqlite3.connect(app.config["DB"], timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def add_user(app: Flask, username: str, password: str, role: str) -> None:
    """Create a validated account with a hashed password."""
    if not username.strip() or len(password) < 10 or role not in ("beta", "research"):
        raise ValueError("用户名必填，密码至少 10 位，角色为 beta 或 research")
    with database(app) as db:
        db.execute(
            "INSERT INTO users(name,password,role) VALUES(?,?,?)",
            (username.strip(), generate_password_hash(password), role),
        )


def initialize_database(app: Flask, recover: bool) -> None:
    """Initialize the schema and recover interrupted evaluation jobs."""
    with database(app) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(
            Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        )
        if "sample_id" not in {
            row["name"] for row in db.execute("PRAGMA table_info(tests)")
        }:
            db.execute("ALTER TABLE tests ADD COLUMN sample_id TEXT DEFAULT ''")
        if recover:
            db.execute(
                (
                    "UPDATE results SET status='failed',error='服务重启中断，请重新测试' WHERE "
                    "status IN ('queued','running')"
                )
            )
            db.execute(
                (
                    "UPDATE tests SET status=CASE WHEN EXISTS(SELECT 1 FROM results "
                    "WHERE test_id=tests.id AND status='completed') THEN 'partial' "
                    "ELSE 'failed' END WHERE status IN ('queued','running')"
                )
            )
