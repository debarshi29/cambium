"""Curation. CLAUDE.md §3.6: runs on a schedule (every N generations), not
continuously. This module is the pass itself; *when* to call it (every N
generations) is the eval harness driver's job (Sprint 5's
scripts/run_evolution.py), not this module's.

Skills:
  - merge near-duplicate signatures
  - deprecate by usage decay (unused for N generations + low success rate)
  - hard cap on active library size (soft deprecation, archived not deleted)

Prompts:
  - retire a variant that loses to its parent on the regression subset
    (in practice: the admission gate already refuses to admit a losing
    variant, so this pass's job is enforcing "exactly one active version
    per node" against the full version history, not re-litigating already-
    rejected candidates)
  - keep exactly one active version per node; superseded versions archived
  - merge near-duplicate variants for the same node

Every action here flips `deprecated = True`. Nothing is ever removed from
a registry's version history — that's the "archived, not deleted" contract
CLAUDE.md §3.6 states explicitly, load-bearing for auditability.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cambium.prompts.registry import PromptRegistry
from cambium.retrieval.index import tokenize
from cambium.skills.registry import SkillRegistry

DEFAULT_DEDUP_SIMILARITY = 0.8
DEFAULT_UNUSED_FOR_N_GENERATIONS = 5
DEFAULT_MIN_SUCCESS_RATE = 0.5
DEFAULT_MAX_ACTIVE_SKILLS = 20


@dataclass
class CurationReport:
    generation: int
    skills_deduped: list = field(default_factory=list)     # [(kept, dropped)]
    skills_decayed: list = field(default_factory=list)      # [name]
    skills_capped: list = field(default_factory=list)        # [name]
    prompts_archived_superseded: list = field(default_factory=list)  # [(node, version)]
    prompts_deduped: list = field(default_factory=list)      # [(node, kept_version, dropped_version)]


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedup_skills(registry: SkillRegistry, threshold: float = DEFAULT_DEDUP_SIMILARITY) -> list:
    """Merge active skills whose retrieval text is near-identical (Jaccard
    similarity over tokens >= threshold) but which weren't caught by the
    admission gate's exact-signature dedup check (CLAUDE.md §3.2 condition
    3) because they have different (category, fn_name) signatures — e.g.
    two skills for genuinely overlapping jobs, admitted from different
    tasks before anyone noticed the overlap. Keeps the higher-success-rate
    skill (ties broken by more invocations, then lexical name order),
    deprecates the other."""
    merged = []
    active = sorted(registry.active(), key=lambda s: s.name)
    dropped_names = set()
    for i, a in enumerate(active):
        if a.name in dropped_names:
            continue
        tokens_a = tokenize(a.retrieval_text())
        for b in active[i + 1:]:
            if b.name in dropped_names:
                continue
            tokens_b = tokenize(b.retrieval_text())
            if _jaccard(tokens_a, tokens_b) >= threshold:
                keep, drop = _rank_pair(a, b)
                registry.deprecate(drop.name, drop.version, reason="near-duplicate")
                dropped_names.add(drop.name)
                merged.append((keep.name, drop.name))
    return merged


def _rank_pair(a, b):
    def key(s):
        return (s.stats.success_rate, s.stats.invocations, s.name)
    return (a, b) if key(a) >= key(b) else (b, a)


def decay_deprecate_skills(
    registry: SkillRegistry,
    current_generation: int,
    unused_for_n_generations: int = DEFAULT_UNUSED_FOR_N_GENERATIONS,
    min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE,
) -> list:
    """Deprecate active skills that are both stale (not used in the last N
    generations, or never used at all if the library itself is older than
    N generations) and weak (success rate below threshold — a skill with no
    invocations at all counts as failing this, not passing by default)."""
    deprecated = []
    for skill in registry.active():
        last_used = skill.stats.last_used_generation
        stale = (last_used is None and current_generation > unused_for_n_generations) or (
            last_used is not None and (current_generation - last_used) > unused_for_n_generations
        )
        weak = skill.stats.invocations == 0 or skill.stats.success_rate < min_success_rate
        if stale and weak:
            registry.deprecate(skill.name, skill.version, reason="usage decay")
            deprecated.append(skill.name)
    return deprecated


def cap_skill_library(registry: SkillRegistry, max_active: int = DEFAULT_MAX_ACTIVE_SKILLS) -> list:
    """Hard cap on active library size. Deprecates the lowest-value skills
    (worst success rate, then fewest invocations, then most stale) until at
    or under the cap. Soft deprecation only — see module docstring."""
    active = registry.active()
    if len(active) <= max_active:
        return []
    ranked = sorted(
        active,
        key=lambda s: (s.stats.success_rate, s.stats.invocations, s.stats.last_used_generation or -1),
    )
    to_drop = ranked[: len(active) - max_active]
    for skill in to_drop:
        registry.deprecate(skill.name, skill.version, reason="size cap")
    return [s.name for s in to_drop]


def archive_superseded_prompts(prompt_registry: PromptRegistry) -> list:
    """Enforce 'exactly one active version per node': every version below
    the current max for a node gets explicitly deprecated (archived), not
    just implicitly shadowed by active() picking the max."""
    archived = []
    for node in ("planner", "reflector", "critic"):
        versions = prompt_registry.all_versions(node)
        if not versions:
            continue
        max_version = max(v.version for v in versions)
        for v in versions:
            if v.version != max_version and not v.deprecated:
                prompt_registry.deprecate(node, v.version, reason="superseded")
                archived.append((node, v.version))
    return archived


def dedup_prompts(prompt_registry: PromptRegistry) -> list:
    """Safety net beyond the admission gate's own dedup check (CLAUDE.md
    §3.4 condition 4): if more than one non-deprecated variant for a node
    somehow shares the same parsed params (e.g. imported from elsewhere,
    bypassing admission), keep the one with the better win rate and archive
    the rest."""
    merged = []
    for node in ("planner", "reflector", "critic"):
        live = [v for v in prompt_registry.all_versions(node) if not v.deprecated]
        by_params: dict = {}
        for v in live:
            key = tuple(sorted(v.params().items()))
            by_params.setdefault(key, []).append(v)
        for group in by_params.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda p: (p.stats.wins_vs_parent, p.version), reverse=True)
            keeper, rest = group[0], group[1:]
            for dupe in rest:
                prompt_registry.deprecate(node, dupe.version, reason="near-duplicate")
                merged.append((node, keeper.version, dupe.version))
    return merged


def run_curation(
    skill_registry: SkillRegistry,
    prompt_registry: PromptRegistry,
    generation: int,
    dedup_similarity: float = DEFAULT_DEDUP_SIMILARITY,
    unused_for_n_generations: int = DEFAULT_UNUSED_FOR_N_GENERATIONS,
    min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE,
    max_active_skills: int = DEFAULT_MAX_ACTIVE_SKILLS,
) -> CurationReport:
    report = CurationReport(generation=generation)
    report.skills_deduped = dedup_skills(skill_registry, dedup_similarity)
    report.skills_decayed = decay_deprecate_skills(
        skill_registry, generation, unused_for_n_generations, min_success_rate
    )
    report.skills_capped = cap_skill_library(skill_registry, max_active_skills)
    report.prompts_archived_superseded = archive_superseded_prompts(prompt_registry)
    report.prompts_deduped = dedup_prompts(prompt_registry)
    return report
