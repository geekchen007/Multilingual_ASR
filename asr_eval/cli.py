"""Command-line server and account administration."""

import argparse
import getpass

from .application import create_app
from .database import add_user


def main() -> None:
    """Run the development server or create an account interactively."""
    parser = argparse.ArgumentParser(description="多语言 ASR 测评平台")
    parser.add_argument(
        "command", choices=["serve", "create-user"], nargs="?", default="serve"
    )
    parser.add_argument("--username")
    parser.add_argument("--role", choices=["beta", "research"], default="beta")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5080, type=int)
    args = parser.parse_args()
    application = create_app(recover=args.command == "serve")
    if args.command == "create-user":
        password = getpass.getpass("Password (at least 10 characters): ")
        add_user(application, args.username or input("Username: "), password, args.role)
        print("User created.")
    else:
        application.run(
            host=args.host,
            port=args.port,
            threaded=True,
            debug=False,
            use_reloader=False,
        )
