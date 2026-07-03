"""Command-line entry point for the KausaMemory MCP stdio server.

Run it directly so any MCP client can spawn it over stdio:

    python -m kausamemory.mcp
    python -m kausamemory.mcp --db /path/to/memory.db

The database path can also be set with the KAUSAMEMORY_DB environment variable.
This is Sovereign mode: local, on-device, no payment gate.
"""

from __future__ import annotations

import argparse
import os

from .interfaces.mcp_server import run_stdio


def main() -> None:
    parser = argparse.ArgumentParser(prog="kausamemory.mcp", description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get("KAUSAMEMORY_DB", "kausamemory.db"),
        help="path to the SQLite memory database (default: kausamemory.db "
        "or the KAUSAMEMORY_DB environment variable)",
    )
    args = parser.parse_args()
    run_stdio(db_path=args.db)


if __name__ == "__main__":
    main()
