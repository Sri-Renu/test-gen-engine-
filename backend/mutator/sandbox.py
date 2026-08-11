"""
Sandbox Runner — safe execution wrapper.

For mutation testing we use mutmut directly (via MutationRunner).
This module handles plain pytest runs for the generate→validate loop
and provides the Docker wrapper for production deployments.

In dev: use_docker=False runs pytest/mutmut directly as subprocesses.
In prod: use_docker=True wraps everything in the Docker sandbox container.
"""

from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass


SANDBOX_IMAGE = "test-gen-sandbox"
DEFAULT_TIMEOUT = 60


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxRunner:
    """
    Run pytest safely against generated test files.

    use_docker=False → direct subprocess (dev mode, no Docker needed)
    use_docker=True  → Docker container with --network none (production)
    """

    def __init__(
        self,
        image: str = SANDBOX_IMAGE,
        timeout: int = DEFAULT_TIMEOUT,
        use_docker: bool = True,
    ):
        self.image = image
        self.timeout = timeout
        self.use_docker = use_docker

    def run_pytest(self, source_code: str, test_code: str) -> SandboxResult:
        """Run pytest on generated tests. Returns pass/fail + output."""
        with tempfile.TemporaryDirectory(prefix="testgen_pytest_") as tmp:
            work = Path(tmp)
            (work / "source.py").write_text(source_code)
            (work / "test_generated.py").write_text(test_code)

            cmd = self._build_cmd(
                work,
                ["python", "-m", "pytest", "test_generated.py",
                 "-v", "--timeout=10", "--tb=short"],
            )
            return self._run(cmd, cwd=work if not self.use_docker else None)

    def _build_cmd(self, work: Path, inner: list[str]) -> list[str]:
        if not self.use_docker:
            return inner
        return [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", "256m",
            "--cpus", "1.0",
            "--user", "sandbox",
            "-v", f"{work}:/sandbox:rw",
            "-w", "/sandbox",
            self.image,
        ] + inner

    def _run(self, cmd: list[str], cwd: Path | None = None) -> SandboxResult:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(cwd) if cwd else None,
            )
            return SandboxResult(
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                exit_code=-1, stdout="",
                stderr=f"Timed out after {self.timeout}s",
                timed_out=True,
            )
        except FileNotFoundError as e:
            return SandboxResult(
                exit_code=-1, stdout="",
                stderr=str(e),
            )