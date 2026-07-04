"""Command-line entry point for the KausaMemory Console.

Run it to open a local dashboard over your memory:
    python -m kausamemory.console
    python -m kausamemory.console --db /path/to/memory.db --port 8787

Then open http://127.0.0.1:8787 in a browser.

The database path can also be set with the KAUSAMEMORY_DB environment variable.
This is Sovereign mode: local, on-device, nothing leaves the machine.
"""
from __future__ import annotations

import argparse
import os

from .interfaces.console_server import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="kausamemory.console", description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get("KAUSAMEMORY_DB", "kausamemory.db"),
        help="path to the SQLite memory database (default: kausamemory.db "
        "or the KAUSAMEMORY_DB environment variable)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8787, help="bind port (default: 8787)")
    parser.add_argument("--namespace", default="default", help="memory namespace (default: default)")
    args = parser.parse_args()
    run(db_path=args.db, host=args.host, port=args.port, namespace=args.namespace)


if __name__ == "__main__":
    main()
