"""`cambium` command-line interface.

    cambium eval            three curves + ablation + hacking audit (+ MLflow)
    cambium baseline        curve 1 only: library-off
    cambium stress          curation stress test, curated vs. uncurated
    cambium llm-demo        live-LLM smoke test (needs GROQ_API_KEY)
    cambium tasks           list the task pack
    cambium library show    summarize a saved library file
    cambium library diff    compare two saved libraries by source fingerprint

Global options pick the sandbox tier (`--sandbox subprocess|docker`) and
logging verbosity. Every command exits non-zero on failure, so it composes
in CI and shell scripts.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from cambium import __version__

log = logging.getLogger("cambium")


# --------------------------------------------------------------------------
# helpers

def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _configure_sandbox(args: argparse.Namespace, deterministic: bool) -> None:
    """--sandbox overrides CAMBIUM_SANDBOX. Caching is on by default for the
    deterministic (scripted) experiments and off for live-LLM runs, and can
    be forced either way."""
    from cambium.sandbox.cache import CachingBackend
    from cambium.sandbox.runner import backend_from_env, set_default_backend

    backend = backend_from_env(args.sandbox)
    use_cache = deterministic if args.sandbox_cache is None else args.sandbox_cache
    if use_cache and not isinstance(backend, CachingBackend):
        backend = CachingBackend(backend)
    if not use_cache and isinstance(backend, CachingBackend):
        backend = backend.inner
    set_default_backend(backend)
    log.debug("sandbox backend: %s", backend.name)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _results_dir(args: argparse.Namespace) -> Path:
    from cambium.eval.experiments import default_results_dir

    return Path(args.out) if args.out else default_results_dir()


def _pack(args: argparse.Namespace):
    from cambium.tasks.pack import DEFAULT_DATA_DIR, load_task_pack

    return load_task_pack(args.tasks or DEFAULT_DATA_DIR)


def _frac(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else f"{n}/{d}"


# --------------------------------------------------------------------------
# commands

def _llm_client(args: argparse.Namespace):
    """GroqClient, optionally behind a record/replay cassette."""
    from cambium.agent.llm_cache import RecordReplayClient
    from cambium.agent.llm_client import GroqClient

    if args.llm_mode == "replay":
        if not args.llm_cache:
            raise ValueError("--llm-mode replay needs --llm-cache PATH")
        return RecordReplayClient(args.llm_cache, mode="replay", model=args.model or None)
    inner = GroqClient(model=args.model) if args.model else GroqClient()
    if not args.llm_cache:
        return inner
    return RecordReplayClient(args.llm_cache, mode=args.llm_mode, inner=inner)


def cmd_eval(args: argparse.Namespace) -> int:
    import functools

    from cambium.agent.loop import run_task_llm
    from cambium.eval.experiments import log_lineage, run_full_eval
    from cambium.library.store import save_library

    live = args.agent == "llm"
    # A replayed cassette is as deterministic as the scripted agent.
    _configure_sandbox(args, deterministic=not live or args.llm_mode == "replay")
    pack = _pack(args)
    runner = None
    client = None
    if live:
        client = _llm_client(args)
        runner = functools.partial(run_task_llm, client=client)
    outcome = run_full_eval(pack, generations=args.generations, freeze_at=args.freeze_at,
                            task_runner=runner)
    report = outcome.report
    if live:
        report["agent"] = {"kind": "llm", "model": client.model, "llm_mode": args.llm_mode}

    off = report["curve_1_library_off"]
    print(f"curve 1  library-off                 held-out {_frac(off['solved'], off['total'])}")
    print("curve 2  library-on, both evolving")
    for r in outcome.both.records:
        print(f"           gen {r.generation}: held-out {_frac(r.heldout_solved, r.heldout_total):<12} "
              f"train {r.train_solved}/{r.train_total}  skills={r.num_active_skills}  "
              f"recall@1={r.recall_at_1:.0%}"
              + (f"  recall@{r.k}={r.recall_at_k:.0%}" if r.k > 1 else ""))
    frozen = report["curve_3_frozen_at_gen"]
    print(f"curve 3  frozen at gen {frozen['frozen_at']}              "
          f"held-out {_frac(frozen['solved'], frozen['total'])}")
    print("ablation (final generation)")
    for name, res in (("tools-only", outcome.tools_only), ("prompts-only", outcome.prompts_only),
                      ("both", outcome.both)):
        last = res.records[-1]
        print(f"           {name:<13} held-out {_frac(last.heldout_solved, last.heldout_total):<12} "
              f"train {last.train_solved}/{last.train_total}")
    print(f"hacking audit: {len(outcome.findings)} finding(s)")
    for f in outcome.findings:
        print(f"  [{f.kind}] {f.subject}")

    suffix = "_llm" if live else ""
    out_dir = _results_dir(args)
    _write_json(out_dir / f"eval_report{suffix}.json", report)
    final = outcome.both.records[-1]
    save_library(out_dir / f"library_both_evolving{suffix}.json", final.skill_registry,
                 final.prompt_registry, generation=final.generation,
                 metadata={"run": f"both-evolving{suffix}", "generations": args.generations,
                           **report.get("agent", {})})
    print(f"written to {out_dir}")
    if live and hasattr(client, "hits"):
        print(f"llm cassette: {client.hits} replayed, {client.calls} live call(s) -> {args.llm_cache}")

    if not args.no_mlflow:
        log_lineage(outcome, pack, tracking_uri=args.tracking_uri,
                    run_name=f"both-evolving{suffix}", extra_params=report.get("agent"))
        print("lineage logged to MLflow")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    from cambium.eval.experiments import run_baseline

    _configure_sandbox(args, deterministic=True)
    report = run_baseline(_pack(args))
    for split in ("train", "heldout"):
        print(f"{split:<8} {_frac(report[split]['solved'], report[split]['total'])}")
    path = _write_json(_results_dir(args) / "baseline.json", report)
    print(f"written to {path}")
    return 0


def cmd_stress(args: argparse.Namespace) -> int:
    from cambium.eval.stress import StressConfig, run_stress

    _configure_sandbox(args, deterministic=True)
    pack = _pack(args)
    base = StressConfig(generations=args.generations, variants_per_generation=args.variants,
                        max_active_skills=args.cap, seed=args.seed)
    arms = {"curated": base}
    if not args.curated_only:
        arms["uncurated"] = StressConfig(**{**asdict(base), "curation": False})

    report: dict = {"config": asdict(base)}
    for label, config in arms.items():
        result = run_stress(pack, config)
        report[label] = [r.to_dict() for r in result.records]
        last = result.records[-1]
        print(f"{label:<10} gen {last.generation}: active={last.active_skills} "
              f"versions={last.total_versions} held-out {_frac(last.heldout_solved, last.heldout_total)} "
              f"recall@{last.k}={last.recall_at_k:.0%}")
    path = _write_json(_results_dir(args) / "curation_stress.json", report)
    print(f"written to {path}")
    return 0


def cmd_llm_demo(args: argparse.Namespace) -> int:
    from cambium.agent.llm_cache import LLMCacheMiss
    from cambium.agent.llm_client import GroqConfigError
    from cambium.agent.loop import run_task_llm
    from cambium.prompts.defaults import seed_default_registry
    from cambium.skills.registry import SkillRegistry

    _configure_sandbox(args, deterministic=False)
    pack = _pack(args)
    client = _llm_client(args)
    prompts = seed_default_registry()
    skills = SkillRegistry()

    seen, tasks = set(), []
    for task in pack.train:
        if task.category not in seen:
            seen.add(task.category)
            tasks.append(task)
    tasks = tasks[: args.limit] if args.limit else tasks

    print(f"model: {client.model}   tasks: {len(tasks)}")
    solved = 0
    for task in tasks:
        try:
            outcome = run_task_llm(task, 1, skills, prompts.active("planner"), prompts.active("reflector"),
                                   prompts.active("critic"), pack, client)
        except (GroqConfigError, LLMCacheMiss) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        solved += outcome.solved
        admitted = [a for a in outcome.admission_attempts if a.admitted]
        note = " (skill admitted)" if admitted else ""
        print(f"  {task.id:<26} {'SOLVED' if outcome.solved else 'failed':<7} via {outcome.strategy}{note}")
    print(f"solved {solved}/{len(tasks)}; active skills: {len(skills)}")
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    pack = _pack(args)
    tasks = pack.tasks if args.split == "all" else (pack.train if args.split == "train" else pack.heldout)
    for t in tasks:
        print(f"{t.id:<26} {t.split:<8} {t.category:<20} {t.fn_name}")
    print(f"{len(tasks)} task(s)")
    return 0


def cmd_library_show(args: argparse.Namespace) -> int:
    from cambium.library.store import load_library

    snap = load_library(args.path)
    print(f"generation: {snap.generation}   metadata: {json.dumps(snap.metadata)}")
    print("active skills:")
    for s in sorted(snap.skills.active(), key=lambda s: s.name):
        print(f"  {s.key():<36} {s.fingerprint()}  uses={s.stats.invocations:<4} "
              f"success={s.stats.success_rate:.0%}")
    archived = [s for s in snap.skills.all_skills() if s.deprecated]
    print(f"archived skill versions: {len(archived)}")
    print("active prompts:")
    for node in snap.prompts.nodes():
        p = snap.prompts.active(node)
        print(f"  {node:<10} v{p.version}  {p.params()}")
    return 0


def cmd_library_diff(args: argparse.Namespace) -> int:
    from cambium.library.store import load_library

    a, b = load_library(args.a), load_library(args.b)
    fa = {s.name: s.fingerprint() for s in a.skills.active()}
    fb = {s.name: s.fingerprint() for s in b.skills.active()}
    added = sorted(set(fb) - set(fa))
    removed = sorted(set(fa) - set(fb))
    changed = sorted(n for n in set(fa) & set(fb) if fa[n] != fb[n])
    for n in added:
        print(f"+ {n}")
    for n in removed:
        print(f"- {n}")
    for n in changed:
        print(f"~ {n}  {fa[n]} -> {fb[n]}")
    for node in sorted(set(a.prompts.nodes()) | set(b.prompts.nodes())):
        pa, pb = a.prompts.active(node).params(), b.prompts.active(node).params()
        if pa != pb:
            print(f"~ prompt:{node}  {pa} -> {pb}")
    identical = not (added or removed or changed)
    print("identical active skills" if identical else
          f"{len(added)} added, {len(removed)} removed, {len(changed)} changed")
    return 0 if identical or not args.exit_code else 1


# --------------------------------------------------------------------------
# parser

def _add_llm_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", help="Groq model id (default: $GROQ_MODEL)")
    p.add_argument("--llm-cache", metavar="PATH",
                   help="JSONL cassette recording every prompt/response (cambium.agent.llm_cache)")
    p.add_argument("--llm-mode", choices=("record", "replay", "auto"), default="auto",
                   help="cassette mode: replay runs offline, with no API key")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sandbox", choices=("subprocess", "docker"),
                        help="sandbox tier (default: $CAMBIUM_SANDBOX or subprocess)")
    cache = common.add_mutually_exclusive_group()
    cache.add_argument("--sandbox-cache", dest="sandbox_cache", action="store_true", default=None,
                       help="memoize sandbox verdicts (default: on for scripted runs)")
    cache.add_argument("--no-sandbox-cache", dest="sandbox_cache", action="store_false",
                       help="disable verdict memoization")
    common.add_argument("--tasks", metavar="DIR", help="task pack directory (default: bundled pack)")
    common.add_argument("--out", metavar="DIR", help="results directory (default: ./results)")
    common.add_argument("--log-level", default="WARNING",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))

    parser = argparse.ArgumentParser(prog="cambium", description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", action="version", version=f"cambium {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("eval", parents=[common], help="three curves, ablation, hacking audit")
    p.add_argument("--generations", type=int, default=4)
    p.add_argument("--freeze-at", type=int, default=2)
    p.add_argument("--no-mlflow", action="store_true", help="skip MLflow lineage logging")
    p.add_argument("--tracking-uri", help="MLflow tracking URI (default: sqlite:///mlruns.db)")
    p.add_argument("--agent", choices=("scripted", "llm"), default="scripted",
                   help="scripted stand-in (default, reproducible) or the live LLM (docs/adr/0012)")
    _add_llm_args(p)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("baseline", parents=[common], help="library-off baseline (curve 1)")
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("stress", parents=[common], help="curation stress test")
    p.add_argument("--generations", type=int, default=25)
    p.add_argument("--variants", type=int, default=4, help="noisy proposals per generation")
    p.add_argument("--cap", type=int, default=24, help="max active skills")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--curated-only", action="store_true")
    p.set_defaults(func=cmd_stress)

    p = sub.add_parser("llm-demo", parents=[common], help="live-LLM smoke test (needs GROQ_API_KEY)")
    _add_llm_args(p)
    p.add_argument("--limit", type=int, default=0, help="max tasks (default: one per category)")
    p.set_defaults(func=cmd_llm_demo)

    p = sub.add_parser("tasks", parents=[common], help="list the task pack")
    p.add_argument("--split", choices=("all", "train", "heldout"), default="all")
    p.set_defaults(func=cmd_tasks)

    lib = sub.add_parser("library", help="inspect saved libraries")
    lib_sub = lib.add_subparsers(dest="library_command", required=True, metavar="ACTION")
    p = lib_sub.add_parser("show", parents=[common], help="summarize a library file")
    p.add_argument("path")
    p.set_defaults(func=cmd_library_show)
    p = lib_sub.add_parser("diff", parents=[common], help="diff two library files")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--exit-code", action="store_true", help="exit 1 if active skills differ")
    p.set_defaults(func=cmd_library_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.log_level)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # surfaced as a clean one-line error; --log-level DEBUG for the trace
        from cambium.agent.llm_cache import LLMCacheMiss
        from cambium.agent.llm_client import GroqConfigError
        from cambium.library.store import LibraryStoreError
        from cambium.sandbox.runner import SandboxBackendError

        if isinstance(exc, (SandboxBackendError, LibraryStoreError, FileNotFoundError, ValueError,
                            LLMCacheMiss, GroqConfigError)):
            log.debug("command failed", exc_info=True)
            print(f"error: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
