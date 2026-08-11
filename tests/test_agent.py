"""
Tests for the agent layer — prompts, parsing, and codegen.
All LLM calls are mocked: no API key needed to run these.

Run with: pytest tests/test_agent.py -v
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from backend.models import FunctionInfo, Parameter, RaisedError, ParameterKind, ComplexityReport
from backend.agent.prompts import build_reasoning_prompt, build_codegen_prompt
from backend.agent.agent import TestGenerationAgent
from backend.generator.generator import PytestGenerator
from backend.models import AgentResult, TestCase, TestCategory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def discount_fn():
    return FunctionInfo(
        name="calculate_discount",
        module_path="source.py",
        source_code=(
            "def calculate_discount(price: float, discount_percent: float) -> float:\n"
            "    if discount_percent > 100:\n"
            "        raise ValueError(\"Discount can't exceed 100%\")\n"
            "    if discount_percent < 0:\n"
            "        raise ValueError(\"Discount can't be negative\")\n"
            "    return price - (price * discount_percent / 100)\n"
        ),
        parameters=[
            Parameter("price", ParameterKind.POSITIONAL, "float"),
            Parameter("discount_percent", ParameterKind.POSITIONAL, "float"),
        ],
        return_type_hint="float",
        raises=[
            RaisedError("ValueError", 'raise ValueError("Discount can\'t exceed 100%")'),
            RaisedError("ValueError", 'raise ValueError("Discount can\'t be negative")'),
        ],
        has_conditionals=True,
        has_loops=False,
        complexity=ComplexityReport(
            function_name="calculate_discount",
            cyclomatic_complexity=3,
            risk_level="low",
            risk_label="A — Simple",
            maintainability_index=72.5,
            recommendation="Focus on happy path and basic boundaries.",
        ),
    )


@pytest.fixture
def sample_test_cases():
    return [
        TestCase(
            category=TestCategory.HAPPY_PATH,
            description="Normal 10% discount returns correct price",
            inputs={"price": 100.0, "discount_percent": 10.0},
            expected_output="90.0",
            expected_exception=None,
            reasoning="Verifies the core math works for a typical use case",
        ),
        TestCase(
            category=TestCategory.BOUNDARY,
            description="Zero discount returns full price",
            inputs={"price": 100.0, "discount_percent": 0.0},
            expected_output="100.0",
            expected_exception=None,
            reasoning="Lower boundary of discount — should not alter price",
        ),
        TestCase(
            category=TestCategory.BOUNDARY,
            description="Full 100% discount returns zero",
            inputs={"price": 100.0, "discount_percent": 100.0},
            expected_output="0.0",
            expected_exception=None,
            reasoning="Upper boundary — exactly 100% should be valid and return 0",
        ),
        TestCase(
            category=TestCategory.EXCEPTION,
            description="Discount over 100 raises ValueError",
            inputs={"price": 100.0, "discount_percent": 101.0},
            expected_output=None,
            expected_exception="ValueError",
            reasoning="Documented constraint; > 100 must raise",
        ),
        TestCase(
            category=TestCategory.EXCEPTION,
            description="Negative discount raises ValueError",
            inputs={"price": 100.0, "discount_percent": -1.0},
            expected_output=None,
            expected_exception="ValueError",
            reasoning="Negative discount makes no business sense; must raise",
        ),
    ]


@pytest.fixture
def agent_result(discount_fn, sample_test_cases):
    return AgentResult(
        function_name="calculate_discount",
        test_cases=sample_test_cases,
        agent_reasoning_summary=(
            "calculate_discount has two raise paths at boundary values "
            "and arithmetic that must be verified at 0, 100, and typical inputs."
        ),
    )


# ---------------------------------------------------------------------------
# Prompt building tests
# ---------------------------------------------------------------------------

class TestReasoningPrompt:
    def test_includes_function_name(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "calculate_discount" in prompt

    def test_includes_parameters(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "price" in prompt
        assert "discount_percent" in prompt

    def test_includes_type_hints(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "float" in prompt

    def test_includes_raise_paths(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "ValueError" in prompt

    def test_includes_source_code(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "def calculate_discount" in prompt

    def test_includes_dependency_context(self, discount_fn):
        dep = FunctionInfo(
            name="apply_tax",
            module_path="source.py",
            source_code="def apply_tax(price): return price * 1.1",
            parameters=[Parameter("price", ParameterKind.POSITIONAL, "float")],
        )
        prompt = build_reasoning_prompt(discount_fn, [dep])
        assert "apply_tax" in prompt
        assert "Dependency context" in prompt

    def test_survived_mutants_injected(self, discount_fn):
        survived = ["changed > to >= on line 3", "deleted condition on line 5"]
        prompt = build_reasoning_prompt(discount_fn, [], survived_mutants=survived)
        assert "MISSED" in prompt
        assert "changed > to >=" in prompt

    def test_no_survived_mutants_when_empty(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [], survived_mutants=[])
        assert "MISSED" not in prompt

    def test_requests_json_output(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "JSON" in prompt

    def test_complexity_injected_in_prompt(self, discount_fn):
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "Cyclomatic complexity" in prompt
        assert "A — Simple" in prompt
        assert "72.5" in prompt

    def test_high_complexity_triggers_warning(self, discount_fn):
        discount_fn.complexity.cyclomatic_complexity = 8
        discount_fn.complexity.risk_level = "moderate"
        discount_fn.complexity.risk_label = "B — Moderate"
        prompt = build_reasoning_prompt(discount_fn, [])
        # CC=8, needs_deep_testing is True (>=5)
        assert "HIGH COMPLEXITY" in prompt

    def test_no_complexity_no_section(self, discount_fn):
        discount_fn.complexity = None
        prompt = build_reasoning_prompt(discount_fn, [])
        assert "Cyclomatic complexity" not in prompt


class TestCodegenPrompt:
    def test_includes_function_name(self, sample_test_cases):
        prompt = build_codegen_prompt("calculate_discount", sample_test_cases, [])
        assert "calculate_discount" in prompt

    def test_includes_test_count(self, sample_test_cases):
        prompt = build_codegen_prompt("calculate_discount", sample_test_cases, [])
        assert str(len(sample_test_cases)) in prompt

    def test_includes_all_categories(self, sample_test_cases):
        prompt = build_codegen_prompt("calculate_discount", sample_test_cases, [])
        assert "HAPPY_PATH" in prompt or "happy_path" in prompt
        assert "EXCEPTION" in prompt or "exception" in prompt
        assert "BOUNDARY" in prompt or "boundary" in prompt

    def test_includes_expected_exception(self, sample_test_cases):
        prompt = build_codegen_prompt("calculate_discount", sample_test_cases, [])
        assert "ValueError" in prompt


# ---------------------------------------------------------------------------
# Agent parsing tests (mock LLM)
# ---------------------------------------------------------------------------

MOCK_REASONING_RESPONSE = json.dumps({
    "function_name": "calculate_discount",
    "reasoning_summary": "Function has two raise paths and boundary arithmetic.",
    "test_cases": [
        {
            "category": "happy_path",
            "description": "10% discount on 100 returns 90",
            "inputs": {"price": 100.0, "discount_percent": 10.0},
            "expected_output": "90.0",
            "expected_exception": None,
            "reasoning": "Core computation must be correct",
            "requires_mock": False,
            "mock_targets": [],
        },
        {
            "category": "exception",
            "description": "Discount > 100 raises ValueError",
            "inputs": {"price": 100.0, "discount_percent": 150.0},
            "expected_output": None,
            "expected_exception": "ValueError",
            "reasoning": "Documented constraint must be enforced",
            "requires_mock": False,
            "mock_targets": [],
        },
        {
            "category": "boundary",
            "description": "Discount exactly 100 returns 0",
            "inputs": {"price": 100.0, "discount_percent": 100.0},
            "expected_output": "0.0",
            "expected_exception": None,
            "reasoning": "Upper boundary must be valid",
            "requires_mock": False,
            "mock_targets": [],
        },
    ]
})

MOCK_CODE_RESPONSE = '''import pytest
from source import calculate_discount

def test_happy_path_10_percent_discount():
    # Core computation must be correct
    result = calculate_discount(100.0, 10.0)
    assert result == pytest.approx(90.0, rel=1e-6)

def test_exception_discount_over_100():
    # Documented constraint must be enforced
    with pytest.raises(ValueError):
        calculate_discount(100.0, 150.0)

def test_boundary_full_discount():
    # Upper boundary must be valid
    result = calculate_discount(100.0, 100.0)
    assert result == pytest.approx(0.0, abs=1e-9)
'''


def _make_mock_response(text: str):
    mock_content = MagicMock()
    mock_content.text = text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    return mock_response


class TestAgentParsing:
    def test_agent_parses_test_cases(self, discount_fn):
        agent = TestGenerationAgent(api_key="test-key")

        with patch.object(agent._client.messages, "create") as mock_create:
            mock_create.side_effect = [
                _make_mock_response(MOCK_REASONING_RESPONSE),
                _make_mock_response(MOCK_CODE_RESPONSE),
            ]
            result, raw_code = agent.run(discount_fn, dependencies=[])

        assert len(result.test_cases) == 3
        assert result.function_name == "calculate_discount"

    def test_agent_returns_raw_code(self, discount_fn):
        agent = TestGenerationAgent(api_key="test-key")

        with patch.object(agent._client.messages, "create") as mock_create:
            mock_create.side_effect = [
                _make_mock_response(MOCK_REASONING_RESPONSE),
                _make_mock_response(MOCK_CODE_RESPONSE),
            ]
            result, raw_code = agent.run(discount_fn, dependencies=[])

        assert "def test_" in raw_code

    def test_agent_maps_categories_correctly(self, discount_fn):
        agent = TestGenerationAgent(api_key="test-key")

        with patch.object(agent._client.messages, "create") as mock_create:
            mock_create.side_effect = [
                _make_mock_response(MOCK_REASONING_RESPONSE),
                _make_mock_response(MOCK_CODE_RESPONSE),
            ]
            result, _ = agent.run(discount_fn, dependencies=[])

        categories = {tc.category for tc in result.test_cases}
        assert TestCategory.HAPPY_PATH in categories
        assert TestCategory.EXCEPTION in categories
        assert TestCategory.BOUNDARY in categories

    def test_agent_captures_reasoning_summary(self, discount_fn):
        agent = TestGenerationAgent(api_key="test-key")

        with patch.object(agent._client.messages, "create") as mock_create:
            mock_create.side_effect = [
                _make_mock_response(MOCK_REASONING_RESPONSE),
                _make_mock_response(MOCK_CODE_RESPONSE),
            ]
            result, _ = agent.run(discount_fn, dependencies=[])

        assert "raise paths" in result.agent_reasoning_summary

    def test_agent_handles_malformed_json(self, discount_fn):
        agent = TestGenerationAgent(api_key="test-key")

        with patch.object(agent._client.messages, "create") as mock_create:
            mock_create.return_value = _make_mock_response("not valid json {{{")
            result, raw_code = agent.run(discount_fn, dependencies=[])

        assert result.test_cases == []
        assert raw_code is not None   # returns empty placeholder, doesn't crash

    def test_agent_strips_markdown_fences(self, discount_fn):
        agent = TestGenerationAgent(api_key="test-key")
        fenced = f"```json\n{MOCK_REASONING_RESPONSE}\n```"

        with patch.object(agent._client.messages, "create") as mock_create:
            mock_create.side_effect = [
                _make_mock_response(fenced),
                _make_mock_response(MOCK_CODE_RESPONSE),
            ]
            result, _ = agent.run(discount_fn, dependencies=[])

        assert len(result.test_cases) == 3

    def test_agent_handles_unknown_category(self, discount_fn):
        bad_category_response = json.dumps({
            "function_name": "calculate_discount",
            "reasoning_summary": "Test",
            "test_cases": [{
                "category": "completely_made_up_category",
                "description": "some test",
                "inputs": {"price": 100.0, "discount_percent": 10.0},
                "expected_output": "90.0",
                "expected_exception": None,
                "reasoning": "test",
                "requires_mock": False,
                "mock_targets": [],
            }]
        })
        agent = TestGenerationAgent(api_key="test-key")

        with patch.object(agent._client.messages, "create") as mock_create:
            mock_create.side_effect = [
                _make_mock_response(bad_category_response),
                _make_mock_response(MOCK_CODE_RESPONSE),
            ]
            result, _ = agent.run(discount_fn, dependencies=[])

        # Should default to HAPPY_PATH, not crash
        assert result.test_cases[0].category == TestCategory.HAPPY_PATH


# ---------------------------------------------------------------------------
# PytestGenerator tests
# ---------------------------------------------------------------------------

class TestPytestGenerator:
    def test_produces_valid_python(self, agent_result):
        gen = PytestGenerator()
        generated = gen.build(agent_result, MOCK_CODE_RESPONSE)
        import ast
        # Should not raise
        ast.parse(generated.test_code)

    def test_counts_test_functions(self, agent_result):
        gen = PytestGenerator()
        generated = gen.build(agent_result, MOCK_CODE_RESPONSE)
        assert generated.test_count == 3

    def test_includes_header(self, agent_result):
        gen = PytestGenerator()
        generated = gen.build(agent_result, MOCK_CODE_RESPONSE)
        assert "calculate_discount" in generated.test_code
        assert "Auto-generated" in generated.test_code

    def test_includes_pytest_import(self, agent_result):
        # Even if LLM omits it, generator adds it
        code_without_import = MOCK_CODE_RESPONSE.replace("import pytest\n", "")
        gen = PytestGenerator()
        generated = gen.build(agent_result, code_without_import)
        assert "import pytest" in generated.test_code

    def test_fallback_on_syntax_error(self, agent_result):
        broken_code = "def test_foo(:\n    pass"
        gen = PytestGenerator()
        generated = gen.build(agent_result, broken_code)
        # Should use fallback, not crash
        assert generated.test_code is not None
        assert "calculate_discount" in generated.test_code

    def test_adds_mock_import_when_needed(self, discount_fn):
        mock_test_case = TestCase(
            category=TestCategory.DEPENDENCY_MOCK,
            description="apply_tax raises RuntimeError",
            inputs={"price": 100.0, "discount_percent": 10.0},
            expected_output=None,
            expected_exception="RuntimeError",
            reasoning="dependency failure path",
            requires_mock=True,
            mock_targets=["apply_tax"],
        )
        result = AgentResult(
            function_name="calculate_discount",
            test_cases=[mock_test_case],
            agent_reasoning_summary="Test with mocking",
        )
        gen = PytestGenerator()
        generated = gen.build(result, MOCK_CODE_RESPONSE)
        assert "unittest.mock" in generated.test_code or "MagicMock" in generated.test_code or "patch" in generated.test_code

    def test_function_name_stored(self, agent_result):
        gen = PytestGenerator()
        generated = gen.build(agent_result, MOCK_CODE_RESPONSE)
        assert generated.function_name == "calculate_discount"

    def test_source_agent_result_stored(self, agent_result):
        gen = PytestGenerator()
        generated = gen.build(agent_result, MOCK_CODE_RESPONSE)
        assert generated.source_agent_result is agent_result