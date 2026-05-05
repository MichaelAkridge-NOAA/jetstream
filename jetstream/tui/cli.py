"""
CLI entry point for the JetStream TUI.

Usage:
    jetstream-tui                 # launch TUI
    jetstream-tui --help

Registered as the 'jetstream-tui' console_scripts entry in pyproject.toml.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jetstream-tui",
        description="NOAA JetStream — Terminal User Interface",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )

    args = parser.parse_args()

    if args.version:
        try:
            from jetstream import __version__
            print(f"jetstream-tui {__version__}")
        except Exception:
            print("jetstream-tui (version unknown)")
        sys.exit(0)

    # Windows: ensure UTF-8 output for Unicode symbols
    if sys.platform == "win32":
        import os
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            import codecs
            if hasattr(sys.stdout, "buffer"):
                sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
            if hasattr(sys.stderr, "buffer"):
                sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")
        except Exception:
            pass

    try:
        from .app import run
        run()
    except ImportError as e:
        print(
            f"ERROR: Could not import Textual. "
            f"Install it with:  pip install textual\n\nDetails: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
