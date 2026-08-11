"""
Mutation Runner — Stage 5 of the pipeline.

Supports mutmut 3.x (the current version).

mutmut 3.x workflow:
  1. Write source.py + test_generated.py + setup.cfg into a temp dir
  2. Run: mutmut run
  3. Run: mutmut results --all true   → parse killed/survived counts
  4. For each survived mutant: mutmut show <name> → get the diff
  5. Build MutationReport with survived diffs fed back to agent

Key differences from mutmut 2.x:
  - Config goes in setup.cfg [mutmut] section, not CLI flags
  - Results format: "  source.x_fn__mutmut_N: killed/survived"
  - Show format: diff with "# mutant_name: status" header
"""

from __future__ import annotations
import re
import subprocess
import tempfile
from pathlib import Path

from backend.models import MutantResult, MutationReport


DEFAULT_TIMEOUT = 180   # mutmut can be slow on large functions


class MutationRunner:
    """
    Orchestrate mutmut 3.x and return a structured MutationReport.

    Usage:
        runner = MutationRunner()
        report = runner.run("calculate_discount", source_code, test_code)
        print(f"Score: {report.mutation_score:.1f}%")
        print("Survived:", report.survived_descriptions)
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout

    def run(
        self,
        function_name: str,
        source_code: str,
        test_code: str,
    ) -> MutationReport:
        """Run mutmut and return a MutationReport."""
        with tempfile.TemporaryDirectory(prefix="testgen_mutmut_") as tmp:
            work = Path(tmp)
            self._write_workspace(work, source_code, test_code)

            # Step 1: run mutation testing
            run_result = self._run_cmd(
                ["mutmut", "run"], cwd=work
            )

            if run_result["timed_out"]:
                return self._timeout_report(function_name)

            # Step 2: collect results
            results_output = self._run_cmd(
                ["mutmut", "results", "--all", "true"], cwd=work
            )["stdout"]

            # Step 3: parse counts
            mutant_lines = self._parse_result_lines(results_output)
            killed   = sum(1 for _, s in mutant_lines if s == "killed")
            survived = sum(1 for _, s in mutant_lines if s == "survived")
            timed_out_count = sum(1 for _, s in mutant_lines if s == "timeout")
            total = killed + survived + timed_out_count
            score = (killed / total * 100) if total > 0 else 0.0

            # Step 4: get diffs for survived mutants (for feedback loop)
            survived_names = [n for n, s in mutant_lines if s == "survived"]
            survived_diffs = self._get_survived_diffs(survived_names, work)

            # Step 5: build MutantResult list
            mutant_results = self._build_mutant_results(mutant_lines, work)

            return MutationReport(
                function_name=function_name,
                total_mutants=total,
                killed=killed,
                survived=survived,
                timed_out=timed_out_count,
                mutation_score=round(score, 1),
                mutant_results=mutant_results,
                survived_descriptions=survived_diffs,
            )

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    def _write_workspace(self, work: Path, source_code: str, test_code: str):
        (work / "source.py").write_text(source_code)
        (work / "test_generated.py").write_text(test_code)
        # mutmut 3.x requires setup.cfg with [mutmut] section
        (work / "setup.cfg").write_text(
            "[mutmut]\n"
            "source_paths=source.py\n"
            "test_command=python -m pytest test_generated.py -x -q --timeout=10\n"
        )

    # ------------------------------------------------------------------
    # Subprocess
    # ------------------------------------------------------------------

    def _run_cmd(self, cmd: list[str], cwd: Path) -> dict:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return {
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "exit_code": proc.returncode,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"Timed out after {self.timeout}s",
                "exit_code": -1,
                "timed_out": True,
            }
        except FileNotFoundError:
            return {
                "stdout": "",
                "stderr": "mutmut not found. Run: pip install mutmut",
                "exit_code": -1,
                "timed_out": False,
            }

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_result_lines(self, output: str) -> list[tuple[str, str]]:
        """
        Parse mutmut results output into list of (mutant_name, status).

        Output lines look like:
            source.x_calculate_discount__mutmut_3: survived
            source.x_calculate_discount__mutmut_1: killed
        """
        results = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # Match: "some.mutant_name: status"
            match = re.match(r"^(.+?):\s*(killed|survived|timeout|suspicious)$", line)
            if match:
                name, status = match.group(1).strip(), match.group(2).strip()
                results.append((name, status))
        return results

    def _get_survived_diffs(
        self, survived_names: list[str], work: Path
    ) -> list[str]:
        """
        For each survived mutant, run `mutmut show <name>` to get
        the diff. These go into survived_descriptions for the feedback loop.
        The agent reads these to understand exactly what mutations its
        tests didn't catch.
        """
        diffs = []
        for name in survived_names[:10]:  # cap at 10 to avoid huge prompts
            result = self._run_cmd(["mutmut", "show", name], cwd=work)
            diff_text = self._extract_diff(result["stdout"], name)
            if diff_text:
                diffs.append(diff_text)
        return diffs

    def _extract_diff(self, show_output: str, mutant_name: str) -> str:
        """
        Extract the meaningful diff lines from mutmut show output.

        Show output format:
            # source.x_...__mutmut_3: survived
            --- source.py
            +++ source.py
            @@ -1,6 +1,6 @@
             def calculate_discount(...):
            -    if discount_percent > 100:
            +    if discount_percent >= 100:
        """
        lines = show_output.splitlines()
        diff_lines = []
        in_diff = False

        for line in lines:
            if line.startswith("---") or line.startswith("+++"):
                in_diff = True
                continue
            if in_diff and (line.startswith("-") or line.startswith("+")):
                diff_lines.append(line)

        if diff_lines:
            short_name = mutant_name.split("__mutmut_")[-1]
            change = " | ".join(diff_lines[:4])
            return f"Mutant #{short_name}: {change}"

        return f"Mutant: {mutant_name} (survived — no diff extracted)"

    def _build_mutant_results(
        self,
        mutant_lines: list[tuple[str, str]],
        work: Path,
    ) -> list[MutantResult]:
        results = []
        for name, status in mutant_lines:
            diff_snippet = ""
            if status == "survived":
                show = self._run_cmd(["mutmut", "show", name], cwd=work)
                diff_snippet = self._extract_diff(show["stdout"], name)

            results.append(MutantResult(
                mutant_id=name,
                status=status,
                description=f"{name}: {status}",
                diff_snippet=diff_snippet,
            ))
        return results

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def _timeout_report(self, function_name: str) -> MutationReport:
        return MutationReport(
            function_name=function_name,
            total_mutants=0,
            killed=0,
            survived=0,
            timed_out=1,
            mutation_score=0.0,
            survived_descriptions=["Mutation testing timed out — try a simpler function."],
        )