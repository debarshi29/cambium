"""Curation stress test: 25 generations of noisy near-duplicate proposals,
curated vs. uncurated (cambium.eval.stress, docs/adr/0011).

Thin wrapper around the `cambium stress` CLI command; extra arguments are
passed through (see `cambium stress --help`).

Run:
    python scripts/run_curation_stress.py
"""
import sys

import _pathfix  # noqa: F401

from cambium.cli import main

if __name__ == "__main__":
    sys.exit(main(["stress", *sys.argv[1:]]))
