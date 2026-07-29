"""
Complexity Analyser — computes cyclomatic complexity and a risk score
for each parsed function, using radon.

Why this matters:
  - Complexity 1-4 → simple, generate standard tests
  - Complexity 5-9 → moderate, prioritise boundary + invariant tests  
  - Complexity 10+  → high risk, flag for deep testing, inject warning into prompt

This feeds into the agent prompt so the LLM knows HOW thorough to be.
Elite tools do this. Beginner tools treat a 2-line function and a
200-line function identically.
"""

from __future__ import annotations

from radon.complexity import cc_visit
from radon.metrics import mi_visit

# ComplexityReport lives in models.py — imported here, not redefined
from backend.models import ComplexityReport


# Risk thresholds from radon's standard classification
_RISK_MAP = {
    (1, 4):   ("low",       "A — Simple",        "Focus on happy path and basic boundaries."),
    (5, 9):   ("moderate",  "B — Moderate",      "Prioritise boundary conditions and every branch path."),
    (10, 14): ("high",      "C — Complex",       "Exhaustive testing required. Every branch, every raise."),
    (15, 999):("very_high", "D — Unmaintainable","This function should be refactored. Test every path rigorously."),
}


class ComplexityAnalyser:
    """
    Compute cyclomatic complexity and maintainability index for Python source.

    Usage:
        analyser = ComplexityAnalyser()
        report = analyser.analyse_function("calculate_discount", source_code)
        print(report.risk_label)   # "A — Simple"
    """

    def analyse_function(
        self, function_name: str, source_code: str
    ) -> ComplexityReport:
        """Analyse a single function's source code."""
        cc = self._get_cc(source_code, function_name)
        risk_level, risk_label, recommendation = self._classify(cc)
        mi = self._get_mi(source_code)

        return ComplexityReport(
            function_name=function_name,
            cyclomatic_complexity=cc,
            risk_level=risk_level,
            risk_label=risk_label,
            maintainability_index=round(mi, 1),
            recommendation=recommendation,
        )

    def analyse_all(self, source_code: str) -> dict[str, ComplexityReport]:
        """Analyse all functions in a source file. Returns {name: report}."""
        try:
            results = cc_visit(source_code)
        except Exception:
            return {}

        reports = {}
        for block in results:
            cc = block.complexity
            risk_level, risk_label, recommendation = self._classify(cc)
            mi = self._get_mi(source_code)
            reports[block.name] = ComplexityReport(
                function_name=block.name,
                cyclomatic_complexity=cc,
                risk_level=risk_level,
                risk_label=risk_label,
                maintainability_index=round(mi, 1),
                recommendation=recommendation,
            )
        return reports

    def _get_cc(self, source: str, fn_name: str) -> int:
        try:
            results = cc_visit(source)
            for block in results:
                if block.name == fn_name:
                    return block.complexity
            # If radon didn't find it by name, return the first result
            if results:
                return results[0].complexity
        except Exception:
            pass
        return 1  # default: assume simple

    def _get_mi(self, source: str) -> float:
        try:
            return mi_visit(source, multi=True)
        except Exception:
            return 100.0

    def _classify(self, cc: int) -> tuple[str, str, str]:
        for (low, high), vals in _RISK_MAP.items():
            if low <= cc <= high:
                return vals
        return ("very_high", "D — Unmaintainable", "Refactor before testing.")