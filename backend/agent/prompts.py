"""
Prompt templates for the test generation agent.

Elite feature: ComplexityReport is injected into the reasoning prompt.
High-complexity functions get a stronger directive to exhaustively cover
every branch — the LLM is told the CC score and what it means.
"""

from __future__ import annotations
from backend.models import FunctionInfo, TestCase


REASONING_SYSTEM = """You are an expert software engineer specializing in test coverage and edge case analysis. Your job is to reason deeply about Python functions and identify every scenario worth testing.

You think systematically across these categories:
1. HAPPY_PATH — valid typical inputs, expected return values
2. BOUNDARY — edge values: zero, empty, max, min, exactly at limits
3. INVALID_INPUT — inputs that violate documented constraints (should raise)
4. TYPE_EDGE_CASE — wrong types, None, mixed types Python silently coerces
5. INVARIANT — properties that must ALWAYS hold regardless of input
6. EXCEPTION — every documented raise path with its exact trigger condition
7. DEPENDENCY_MOCK — if function calls others, cases where the dependency fails

For each test case you identify, you must provide:
- category (from list above)
- description (one sentence: what scenario and what is expected)
- inputs (exact values as a Python dict)
- expected_output (exact return value as string, or null if it raises)
- expected_exception (exception class name if it should raise, else null)
- reasoning (why this case catches real bugs — be specific)
- requires_mock (true if a dependency needs to be stubbed)
- mock_targets (list of function names to mock, or empty list)

You MUST respond with ONLY valid JSON — no markdown, no explanation outside the JSON.
JSON schema:
{
  "function_name": "string",
  "reasoning_summary": "string (2-3 sentences on the function's risk profile)",
  "test_cases": [
    {
      "category": "happy_path|boundary|invalid_input|type_edge_case|invariant|exception|dependency_mock",
      "description": "string",
      "inputs": {},
      "expected_output": "string or null",
      "expected_exception": "string or null",
      "reasoning": "string",
      "requires_mock": false,
      "mock_targets": []
    }
  ]
}"""


def build_reasoning_prompt(
    fn: FunctionInfo,
    dependencies: list[FunctionInfo],
    survived_mutants: list[str] | None = None,
) -> str:
    lines = []

    # ── Function facts ────────────────────────────────────────────────
    lines.append("## Function to analyze")
    lines.append(f"Name: {fn.name}")
    lines.append(f"Module: {fn.module_path}")

    params = []
    for p in fn.parameters:
        hint    = f": {p.type_hint}" if p.type_hint else ""
        default = f" = {p.default_value}" if p.default_value else ""
        params.append(f"{p.name}{hint}{default}")
    lines.append(f"Parameters: ({', '.join(params)})")

    if fn.return_type_hint:
        lines.append(f"Return type: {fn.return_type_hint}")
    if fn.docstring:
        lines.append(f"Docstring: {fn.docstring}")

    lines.append(f"Has conditionals: {fn.has_conditionals}")
    lines.append(f"Has loops: {fn.has_loops}")

    if fn.raises:
        lines.append("\nRaise paths:")
        for r in fn.raises:
            lines.append(f"  - {r.exception_type}: {r.condition_snippet.strip()}")

    if fn.calls:
        lines.append(f"\nCalls these functions: {', '.join(fn.calls)}")

    # ── Complexity (elite feature) ────────────────────────────────────
    if fn.complexity:
        c = fn.complexity
        lines.append(f"\n## Complexity analysis")
        lines.append(f"Cyclomatic complexity: {c.cyclomatic_complexity} ({c.risk_label})")
        lines.append(f"Maintainability index: {c.maintainability_index}/100")
        lines.append(f"Testing directive: {c.recommendation}")
        if c.needs_deep_testing:
            lines.append(
                "⚠️  HIGH COMPLEXITY — you MUST cover every branch path exhaustively. "
                "Generate more test cases than you normally would. "
                "Every conditional arm needs its own test case."
            )

    # ── Source code ───────────────────────────────────────────────────
    lines.append("\n## Source code")
    lines.append("```python")
    lines.append(fn.source_code)
    lines.append("```")

    # ── Dependency context ────────────────────────────────────────────
    if dependencies:
        lines.append("\n## Dependency context (functions this calls)")
        for dep in dependencies:
            lines.append(f"\n### {dep.name}")
            lines.append("```python")
            lines.append(dep.source_code)
            lines.append("```")
            if dep.raises:
                lines.append(f"Can raise: {', '.join(r.exception_type for r in dep.raises)}")
            if dep.complexity and dep.complexity.needs_deep_testing:
                lines.append(f"Dependency complexity: {dep.complexity.risk_label} — mock it carefully.")

    # ── Feedback loop: survived mutants ───────────────────────────────
    if survived_mutants:
        lines.append("\n## CRITICAL: Your previous tests MISSED these mutations")
        lines.append("Each survived mutant is a real bug your tests didn't catch.")
        lines.append("You MUST generate new test cases that kill each one:\n")
        for i, mut in enumerate(survived_mutants, 1):
            lines.append(f"  {i}. {mut}")
        lines.append(
            "\nFor each survived mutant, add at least one test targeting "
            "that exact boundary or operator change."
        )

    lines.append(
        "\n## Task\n"
        "Analyze this function thoroughly. Cover ALL categories. "
        "Be specific about exact input values and expected outputs. "
        "Focus especially on operator boundaries (> vs >=, + vs -, etc.).\n"
        "Respond with ONLY the JSON object. No markdown fences."
    )

    return "\n".join(lines)


CODEGEN_SYSTEM = """You are an expert Python test engineer. You receive structured test case specifications and convert them into a complete, runnable pytest file.

Rules:
- Generate ONE pytest function per test case
- Function names: test_{category}_{short_description} (snake_case, max 60 chars)
- Use pytest.raises(ExceptionClass) for exception cases
- Use unittest.mock.patch for dependency mocking
- Add a one-line comment above each test explaining WHY it matters
- The generated file must be self-contained: include all imports
- Import the function under test as: from source import {function_name}
- Use assert statements only — no print, no logging
- For floating point: use pytest.approx(value, rel=1e-6)
- Group tests with a comment header per category

You MUST respond with ONLY the Python code — no markdown fences, no explanation."""


def build_codegen_prompt(
    fn_name: str,
    test_cases: list[TestCase],
    dependencies: list[FunctionInfo],
) -> str:
    lines = []
    lines.append(f"Generate a complete pytest file for function: `{fn_name}`")
    lines.append(f"Import it with: from source import {fn_name}")

    if dependencies:
        lines.append(f"Dependencies that may need mocking: {', '.join(d.name for d in dependencies)}")

    lines.append(f"\nTotal test cases to implement: {len(test_cases)}")
    lines.append("\n## Test case specifications\n")

    for i, tc in enumerate(test_cases, 1):
        lines.append(f"### Test {i}: [{tc.category.value.upper()}]")
        lines.append(f"Description: {tc.description}")
        lines.append(f"Inputs: {tc.inputs}")
        if tc.expected_output is not None:
            lines.append(f"Expected output: {tc.expected_output}")
        if tc.expected_exception:
            lines.append(f"Expected exception: {tc.expected_exception}")
        if tc.requires_mock:
            lines.append(f"Requires mock: {', '.join(tc.mock_targets)}")
        lines.append(f"Reasoning: {tc.reasoning}")
        lines.append("")

    lines.append("\nGenerate the complete pytest file now. Only Python code, no markdown, no explanation.")
    return "\n".join(lines)