"""library-off baseline: score the agent with no skill library at all.
This is curve 1 of CLAUDE.md §4's three curves.

Thin wrapper around the `cambium baseline` CLI command; extra arguments are
passed through (see `cambium baseline --help`).

Run:
    python scripts/run_baseline.py
"""
import sys

import _pathfix  # noqa: F401

from cambium.cli import main

if __name__ == "__main__":
    sys.exit(main(["baseline", *sys.argv[1:]]))
