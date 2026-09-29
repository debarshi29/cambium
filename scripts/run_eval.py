"""Sprint 5: the eval harness -- the three curves (CLAUDE.md §4), the
tools-vs-prompts attribution ablation, the reward-hacking audit, and MLflow
lineage for the whole run.

Thin wrapper around the `cambium eval` CLI command; extra arguments are
passed through (see `cambium eval --help`).

Run:
    python scripts/run_eval.py
"""
import sys

import _pathfix  # noqa: F401

from cambium.cli import main

if __name__ == "__main__":
    sys.exit(main(["eval", *sys.argv[1:]]))
