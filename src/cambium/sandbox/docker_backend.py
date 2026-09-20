"""Container sandbox tier (docs/adr/0009). CLAUDE.md §6: "Subprocess
isolation minimum; container preferred."

Runs the exact same harness as the subprocess tier (same files, same
parent-side judging -- see cambium.sandbox.runner.write_sandbox_dir/judge),
inside a throwaway container that adds the kernel-enforced boundaries the
subprocess tier can't give:

- `--network none`: no network namespace to reach anything with, whatever
  the code does.
- `--read-only` root filesystem, a small `/tmp` tmpfs, and only the per-run
  scratch directory mounted writable.
- `--cap-drop ALL`, `--security-opt no-new-privileges`, runs as `nobody`.
- `--memory` / `--memory-swap` (cgroup, works on every host OS, unlike
  rlimits), `--cpus`, and `--pids-limit` against fork bombs.

The audit hook and rlimits still run inside the container: defense in
depth, and identical violation reporting across both tiers.

Selected with CAMBIUM_SANDBOX=docker (or `cambium --sandbox docker`).
The image defaults to python:3.13-slim and can be pinned by digest with
CAMBIUM_SANDBOX_IMAGE for reproducibility.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from cambium.sandbox.runner import (
    SandboxBackendError,
    SandboxLimits,
    SandboxResult,
    cap_output,
    judge,
    write_sandbox_dir,
)

DEFAULT_IMAGE = "python:3.13-slim"
_DOCKER_INFRA_EXIT_CODES = {125, 126, 127}  # docker run itself failed, not the code


@dataclass
class DockerBackend:
    image: str = DEFAULT_IMAGE
    docker: str = "docker"
    cpus: float = 1.0
    pids_limit: int = 64
    # Container create/start/teardown overhead, added to limits.timeout for
    # the *outer* wall-clock guard. The in-container alarm enforces the real
    # per-candidate timeout, so this only matters if that alarm is defeated.
    startup_grace_seconds: float = 15.0

    name = "docker"

    @staticmethod
    def from_env() -> DockerBackend:
        return DockerBackend(
            image=os.environ.get("CAMBIUM_SANDBOX_IMAGE", DEFAULT_IMAGE),
            docker=os.environ.get("CAMBIUM_DOCKER", "docker"),
        )

    def check_available(self) -> None:
        """Fail loudly up front instead of failing every candidate later."""
        if shutil.which(self.docker) is None:
            raise SandboxBackendError(f"docker CLI {self.docker!r} not found on PATH")
        info = subprocess.run(
            [self.docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=30,
        )
        if info.returncode != 0:
            raise SandboxBackendError(f"docker daemon not reachable: {info.stderr.strip()}")
        image = subprocess.run(
            [self.docker, "image", "inspect", self.image],
            capture_output=True, text=True, timeout=30,
        )
        if image.returncode != 0:
            pull = subprocess.run(
                [self.docker, "pull", "--quiet", self.image],
                capture_output=True, text=True, timeout=600,
            )
            if pull.returncode != 0:
                raise SandboxBackendError(f"cannot pull sandbox image {self.image}: {pull.stderr.strip()}")

    @staticmethod
    def is_available(image: str = DEFAULT_IMAGE) -> bool:
        try:
            DockerBackend(image=image).check_available()
        except (SandboxBackendError, OSError, subprocess.SubprocessError):
            return False
        return True

    def command(self, workdir: Path, container_name: str, limits: SandboxLimits) -> list[str]:
        memory = f"{limits.memory_mb}m"
        return [
            self.docker, "run", "--rm",
            "--name", container_name,
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", "65534:65534",
            "--memory", memory, "--memory-swap", memory,
            "--cpus", str(self.cpus),
            "--pids-limit", str(self.pids_limit),
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--volume", f"{workdir}:/sandbox:rw",
            "--workdir", "/sandbox",
            self.image,
            "python", "-I", "-S", "harness.py", json.dumps(limits.child_config()),
        ]

    def run(self, source: str, fn_name: str, cases: list, limits: SandboxLimits) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="cambium-sbx-") as tmp:
            workdir = Path(tmp).resolve()
            write_sandbox_dir(workdir, source, fn_name, cases)
            # The container runs as `nobody`; it needs to write result.json.
            os.chmod(workdir, 0o777)
            name = f"cambium-sbx-{uuid.uuid4().hex[:12]}"
            try:
                proc = subprocess.run(
                    self.command(workdir, name, limits),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=limits.timeout + self.startup_grace_seconds,
                )
            except subprocess.TimeoutExpired:
                subprocess.run([self.docker, "kill", name], capture_output=True, timeout=30)
                return SandboxResult(False, "timeout", "", f"exceeded {limits.timeout}s timeout", -1)

            stdout = cap_output(proc.stdout, limits.max_output_bytes)
            stderr = cap_output(proc.stderr, limits.max_output_bytes)
            if proc.returncode in _DOCKER_INFRA_EXIT_CODES and not (workdir / "result.json").exists():
                raise SandboxBackendError(f"docker run failed ({proc.returncode}): {stderr.strip()}")
            return judge(workdir, cases, stdout, stderr, proc.returncode)
