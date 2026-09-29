"""Live smoke test: real tasks through the Groq-backed agent loop
(docs/adr/0007). Requires GROQ_API_KEY in .env or the environment. Kept
out of the reproducible curves on purpose: a live model call is neither
deterministic nor free.

Thin wrapper around the `cambium llm-demo` CLI command; extra arguments are
passed through (see `cambium llm-demo --help`).

Run:
    python scripts/run_llm_demo.py
"""
import sys

import _pathfix  # noqa: F401

from cambium.cli import main

if __name__ == "__main__":
    sys.exit(main(["llm-demo", *sys.argv[1:]]))
