"""
Pytest Generator — Stage 3 of the pipeline.

Post-processes LLM output into a guaranteed-valid pytest file:
  1. Validates the code is parseable Python
  2. Ensures required imports exist
  3. Injects a metadata header
  4. Counts test functions
  5. Falls back to a generated skeleton if LLM produces broken code
"""

from __future__ import annotations
import ast
import textwrap
from datetime import datetime, timezone

from backend.models import AgentResult, GeneratedTest


# Only pytest is unconditionally required — sys/os are not needed in tests
REQUIRED_IMPORTS = ["import pytest"]
MOCK_IMPORT = "from unittest.mock import patch, MagicMock"


class PytestGenerator:

    def build(
        self,
        agent_result: AgentResult,
        raw_code: str,
        source_module_path: str = "source",
    ) -> GeneratedTest:
        # 1. Validate
        validated_code, parse_error = self._validate_python(raw_code)
        if parse_error:
            validated_code = self._build_fallback(agent_result, source_module_path)

        # 2. Ensure imports
        final_code = self._ensure_imports(validated_code, agent_result)

        # 3. Header
        header = self._build_header(agent_result)
        final_code = header + "\n\n" + final_code

        # 4. Count
        test_count = self._count_tests(final_code)

        return GeneratedTest(
            function_name=agent_result.function_name,
            test_code=final_code,
            test_count=test_count,
            source_agent_result=agent_result,
        )

    # ------------------------------------------------------------------

    def _validate_python(self, code: str) -> tuple[str, str | None]:
        try:
            ast.parse(code)
            return code, None
        except SyntaxError as e:
            return code, str(e)

    def _ensure_imports(self, code: str, agent_result: AgentResult) -> str:
        lines = code.splitlines()
        missing = []

        for imp in REQUIRED_IMPORTS:
            if not any(imp in line for line in lines):
                missing.append(imp)

        needs_mock = any(tc.requires_mock for tc in agent_result.test_cases)
        if needs_mock and "unittest.mock" not in code:
            missing.append(MOCK_IMPORT)

        if missing:
            return "\n".join(missing) + "\n\n" + code
        return code

    def _build_header(self, agent_result: AgentResult) -> str:
        fn = agent_result.function_name
        count = len(agent_result.test_cases)
        categories = sorted({tc.category.value for tc in agent_result.test_cases})
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        summary = agent_result.agent_reasoning_summary or "No summary."
        wrapped = textwrap.fill(
            summary, width=72,
            initial_indent="    ", subsequent_indent="    "
        )
        return "\n".join([
            '"""',
            f"Auto-generated tests for: {fn}",
            f"Generated:   {timestamp}",
            f"Test cases:  {count}",
            f"Categories:  {', '.join(categories)}",
            "",
            "Agent reasoning:",
            wrapped,
            '"""',
        ])

    def _build_fallback(self, agent_result: AgentResult, source_module_path: str) -> str:
        """Used when the LLM produces unparseable Python."""
        fn = agent_result.function_name
        lines = [
            "import pytest",
            f"from {source_module_path} import {fn}",
            "",
        ]
        for tc in agent_result.test_cases:
            safe = "".join(
                c if c.isalnum() else "_"
                for c in tc.description[:50]
            ).lower().strip("_")
            name = f"test_{tc.category.value}_{safe}"[:79]

            lines.append(f"# {tc.reasoning}")
            lines.append(f"def {name}():")
            args = ", ".join(repr(v) for v in tc.inputs.values())
            if tc.expected_exception:
                lines.append(f"    with pytest.raises({tc.expected_exception}):")
                lines.append(f"        {fn}({args})")
            else:
                lines.append(f"    result = {fn}({args})")
                if tc.expected_output is not None:
                    lines.append(f"    assert result == {tc.expected_output}")
                else:
                    lines.append(f"    assert result is not None")
            lines.append("")

        return "\n".join(lines)

    def _count_tests(self, code: str) -> int:
        try:
            tree = ast.parse(code)
            return sum(
                1 for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")
            )
        except SyntaxError:
            return 0