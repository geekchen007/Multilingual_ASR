"""Backward-compatible CLI and Waitress entry point."""

from asr_eval import create_app
from asr_eval.cli import main
from asr_eval.database import add_user, database

__all__ = ["create_app", "add_user", "database"]

if __name__ == "__main__":
    main()
