"""On-disk persistence for both evolving artifact types.

Until now both registries lived only in memory: every script rebuilt the
library from generation 1, and the only record of what a run admitted was
the MLflow snapshot of *active* skills (no source, no deprecated history).
That is fine for a reproducible demo and useless for anything that needs
to resume a run, diff two runs, or hand a library to someone else.

A library snapshot is a single JSON document:

    {
      "schema_version": 1,
      "generation": <int | null>,
      "metadata": {...},              # free-form: run label, config, git sha
      "skills": {"skills": [...]},    # SkillRegistry.to_dict(), full history
      "prompts": {"prompts": [...]}   # PromptRegistry.to_dict(), full history
    }

Design points:

- **Full version history, deprecated included.** CLAUDE.md §3.6 says
  curation archives, never deletes; persisting only the active set would
  quietly turn every save/load cycle into a delete.
- **Atomic writes.** Written to a sibling temp file and `os.replace`d into
  place, so a crash mid-write never leaves a truncated library behind.
- **Integrity check.** Every skill carries a source fingerprint; loading a
  file whose source was edited by hand fails loudly instead of running
  code that never went through the admission gate.
- **Explicit schema version.** Loading an unknown schema raises rather than
  guessing.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from cambium.prompts.registry import PromptRegistry
from cambium.skills.registry import SkillRegistry

SCHEMA_VERSION = 1


class LibraryStoreError(RuntimeError):
    """Raised for unreadable, corrupt, or incompatible library files."""


@dataclass
class LibrarySnapshot:
    skills: SkillRegistry
    prompts: PromptRegistry
    generation: int | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "generation": self.generation,
            "metadata": dict(self.metadata),
            "skills": self.skills.to_dict(),
            "prompts": self.prompts.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict) -> LibrarySnapshot:
        version = d.get("schema_version")
        if version != SCHEMA_VERSION:
            raise LibraryStoreError(
                f"unsupported library schema_version {version!r} "
                f"(this build reads {SCHEMA_VERSION})"
            )
        try:
            return LibrarySnapshot(
                skills=SkillRegistry.from_dict(d.get("skills", {})),
                prompts=PromptRegistry.from_dict(d.get("prompts", {})),
                generation=d.get("generation"),
                metadata=dict(d.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LibraryStoreError(f"corrupt library file: {exc}") from exc


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save_library(
    path: Path | str,
    skills: SkillRegistry,
    prompts: PromptRegistry,
    generation: int | None = None,
    metadata: dict | None = None,
) -> Path:
    path = Path(path)
    snapshot = LibrarySnapshot(skills, prompts, generation, dict(metadata or {}))
    _atomic_write_text(path, json.dumps(snapshot.to_dict(), indent=2) + "\n")
    return path


def load_library(path: Path | str) -> LibrarySnapshot:
    """Raises FileNotFoundError for a missing file (callers commonly treat
    that as "start a fresh library") and LibraryStoreError for anything
    present but unusable."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise LibraryStoreError(f"cannot read library file {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LibraryStoreError(f"library file {path} is not a JSON object")
    return LibrarySnapshot.from_dict(raw)
