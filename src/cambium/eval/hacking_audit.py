"""Reward-hacking audit. CLAUDE.md §4:

    Skills that special-case a specific eval task, and prompts that leak or
    hard-code eval-specific phrasing/answers, must be detected and reported,
    not suppressed.

Two independent checks, because a hack can be caught at either point:

1. **Gate rejections.** Every `AdmissionResult` with reason "reuse_failed"
   is, by construction, a candidate that solved its origin task but failed
   to generalize — the signature of overfitting. These are successes for
   the project (the gate caught them), reported here as findings, not
   hidden because they reflect well on the system.
2. **Source-level scan of what *did* get admitted.** A secondary,
   independent check on every currently-admitted skill's source, looking
   for literal input->output lookup tables or long input-equality chains —
   patterns consistent with a hack that slipped past the reuse check (e.g.
   if the reuse task's cases happened to coincide with the hack's hardcoded
   values by chance). Finding nothing here is not proof of nothing wrong;
   it's one more check, reported as such.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

from cambium.skills.registry import SkillRegistry


@dataclass
class HackingFinding:
    kind: str  # "gate_rejected_overfit" | "admitted_suspicious_literal_table"
    subject: str  # skill name or admission origin task id
    detail: str


def audit_admission_log(admission_log: list) -> list:
    """admission_log: list of (context_label, AdmissionResult) tuples
    accumulated across a run (e.g. every candidate proposed during
    evolution, admitted or not)."""
    findings = []
    for label, result in admission_log:
        if result.reason == "reuse_failed":
            findings.append(HackingFinding(
                kind="gate_rejected_overfit",
                subject=label,
                detail=f"passed its origin task, rejected on reuse: {result.detail}",
            ))
    return findings


def _looks_like_literal_lookup(source: str) -> str | None:
    """Heuristic AST scan: a dict literal with >=2 string/number keys used
    as the sole return path, or an if/elif chain of >=2 branches each
    comparing a parameter directly to a literal, are both consistent with
    "memorize known cases" rather than "compute the answer"."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and len(node.keys) >= 2:
            if all(isinstance(k, ast.Constant) for k in node.keys if k is not None):
                return "dict literal keyed by >=2 constant values"
        if isinstance(node, ast.If):
            chain_len = 0
            cur = node
            while isinstance(cur, ast.If):
                test = cur.test
                if isinstance(test, ast.Compare) and any(isinstance(c, ast.Constant) for c in test.comparators):
                    chain_len += 1
                cur = cur.orelse[0] if (cur.orelse and isinstance(cur.orelse[0], ast.If)) else None
            if chain_len >= 2:
                return f"if/elif chain of {chain_len} literal-equality branches"
    return None


def audit_admitted_skills(skill_registry: SkillRegistry) -> list:
    findings = []
    for skill in skill_registry.active():
        reason = _looks_like_literal_lookup(skill.source)
        if reason:
            findings.append(HackingFinding(
                kind="admitted_suspicious_literal_table",
                subject=skill.name,
                detail=reason,
            ))
    return findings


def run_audit(skill_registry: SkillRegistry, admission_log: list) -> list:
    return audit_admission_log(admission_log) + audit_admitted_skills(skill_registry)
