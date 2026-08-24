"""
Integration tests for the full pipeline.
Mocks the Anthropic API — no key needed, no cost.

Run with: pytest tests/test_pipeline.py -v
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from backend.pipeline import Pipeline
from backend.models import TestCategory


# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

DISCOUNT_SOURCE = '''
def calculate_discount(price: float, discount_percent: float) -> float:
    """Apply a percentage discount to a price."""
    if discount_percent > 100:
        raise ValueError("Discount can't exceed 100%")
    if discount_percent < 0:
        raise ValueError("Discount can't be negative")
    return price - (price * discount_percent / 100)
'''

MOCK_REASONING = json.dumps({
    "function_name": "calculate_discount",
    "reasoning_summary": "Two raise paths at boundary values. Arithmetic needs verification at 0, 100, and typical inputs.",
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
            "category": "boundary",
            "description": "Zero discount returns full price",
            "inputs": {"price": 100.0, "discount_percent": 0.0},
            "expected_output": "100.0",
            "expected_exception": None,
            "reasoning": "Lower boundary — no reduction",
            "requires_mock": False,
            "mock_targets": [],
        },
        {
            "category": "boundary",
            "description": "Exactly 100% discount returns 0",
            "inputs": {"price": 100.0, "discount_percent": 100.0},
            "expected_output": "0.0",
            "expected_exception": None,
            "reasoning": "Upper boundary must be valid and return zero",
            "requires_mock": False,
            "mock_targets": [],
        },
        {
            "category": "exception",
            "description": "Discount over 100 raises ValueError",
            "inputs": {"price": 100.0, "discount_percent": 101.0},
            "expected_output": None,
            "expected_exception": "ValueError",
            "reasoning": "Documented constraint must raise",
            "requires_mock": False,
            "mock_targets": [],
        },
        {
            "category": "exception",
            "description": "Negative discount raises ValueError",
            "inputs": {"price": 100.0, "discount_percent": -1.0},
            "expected_output": None,
            "expected_exception": "ValueError",
            "reasoning": "Negative discount is invalid",
            "requires_mock": False,
            "mock_targets": [],
        },
    ]
})

MOCK_CODE = '''import pytest
from source import calculate_discount

def test_happy_path_10_percent():
    result = calculate_discount(100.0, 10.0)
    assert result == pytest.approx(90.0)

def test_boundary_zero_discount():
    result = calculate_discount(100.0, 0.0)
    assert result == pytest.approx(100.0)

def test_boundary_full_discount():
    result = calculate_discount(100.0, 100.0)
    assert result == pytest.approx(0.0)

def test_exception_over_100():
    with pytest.raises(ValueError):
        calculate_discount(100.0, 101.0)

def test_exception_negative():
    with pytest.raises(ValueError):
        calculate_discount(100.0, -1.0)
'''


def _mock_response(text: str):
    content = MagicMock()
    content.text = text
    resp = MagicMock()
    resp.content = [content]
    return resp


def make_pipeline() -> Pipeline:
    return Pipeline(
        api_key="test-key",
        use_docker=False,
        max_feedback_loops=1,
        use_cache=False,   # never use cache in tests — each run must be independent
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineNoMutation:

    def test_complete_status_on_success(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [
                _mock_response(MOCK_REASONING),
                _mock_response(MOCK_CODE),
            ]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.status == "complete"
        assert result.error is None

    def test_function_info_populated(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.function_info is not None
        assert result.function_info.name == "calculate_discount"

    def test_agent_result_populated(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.agent_result is not None
        assert len(result.agent_result.test_cases) == 5

    def test_generated_test_populated(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.generated_test is not None
        assert result.generated_test.test_count == 5
        assert "def test_" in result.generated_test.test_code

    def test_test_code_has_correct_import(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert "from source import calculate_discount" in result.generated_test.test_code

    def test_no_mutation_report_when_disabled(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE, run_mutation=False)

        assert result.mutation_report is None
        assert result.mutation_score is None

    def test_target_function_selection(self):
        source = DISCOUNT_SOURCE + "\ndef helper(x): return x\n"
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(source, target_function="calculate_discount")

        assert result.function_info.name == "calculate_discount"

    def test_unknown_target_function_fails_gracefully(self):
        pipeline = make_pipeline()
        result = pipeline.run_from_source(DISCOUNT_SOURCE, target_function="nonexistent")

        assert result.status == "failed"
        assert "nonexistent" in result.error
        assert "Available" in result.error

    def test_empty_source_fails_gracefully(self):
        pipeline = make_pipeline()
        result = pipeline.run_from_source("")

        assert result.status == "failed"
        assert result.error is not None

    def test_llm_called_exactly_twice(self):
        """No double-calls — exactly 2 LLM calls per run."""
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            pipeline.run_from_source(DISCOUNT_SOURCE)

        assert mock_llm.call_count == 2

    def test_test_categories_present(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        cats = {tc.category for tc in result.agent_result.test_cases}
        assert TestCategory.HAPPY_PATH in cats
        assert TestCategory.EXCEPTION in cats
        assert TestCategory.BOUNDARY in cats

    def test_reasoning_summary_populated(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.agent_result.agent_reasoning_summary != ""

    def test_job_id_assigned(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.job_id is not None
        assert len(result.job_id) > 0

    def test_dependency_context_passed_to_agent(self):
        """When source has multiple functions, dependencies are resolved and passed."""
        source = '''
def apply_tax(price: float) -> float:
    return price * 1.1

def calculate_discount(price: float, discount_percent: float) -> float:
    if discount_percent > 100:
        raise ValueError("Too high")
    discounted = price - (price * discount_percent / 100)
    return apply_tax(discounted)
'''
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(source, target_function="calculate_discount")

        # Verify the pipeline didn't crash and got a complete result
        assert result.status == "complete"
        # The reasoning prompt should have included apply_tax context
        first_call_prompt = mock_llm.call_args_list[0]
        prompt_content = str(first_call_prompt)
        assert "apply_tax" in prompt_content


# ---------------------------------------------------------------------------
# Elite feature tests
# ---------------------------------------------------------------------------

class TestComplexityIntegration:
    """Complexity is computed and attached to every pipeline result."""

    def test_complexity_attached_to_function_info(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.function_info.complexity is not None

    def test_complexity_has_cc_score(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        cc = result.function_info.complexity.cyclomatic_complexity
        assert isinstance(cc, int)
        assert cc >= 1

    def test_complexity_has_risk_level(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result.function_info.complexity.risk_level in (
            "low", "moderate", "high", "very_high"
        )

    def test_complexity_has_maintainability_index(self):
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(DISCOUNT_SOURCE)

        mi = result.function_info.complexity.maintainability_index
        assert 0.0 <= mi <= 100.0

    def test_high_complexity_function_flagged(self):
        """A function with many branches gets moderate/high risk level."""
        complex_source = '''
def process(x, y, z, flag):
    if x > 0:
        if y > 0:
            if z > 0:
                if flag:
                    return x + y + z
                else:
                    return x * y * z
            else:
                return x - z
        elif y < 0:
            return x - y
        else:
            return 0
    elif x < 0:
        return -x
    else:
        return y + z
'''
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result = pipeline.run_from_source(complex_source)

        cc = result.function_info.complexity.cyclomatic_complexity
        assert cc >= 5, f"Expected CC >= 5, got {cc}"
        assert result.function_info.complexity.needs_deep_testing is True

    def test_complexity_injected_into_agent_prompt(self):
        """Complexity info appears in the reasoning prompt sent to the LLM."""
        pipeline = make_pipeline()
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            pipeline.run_from_source(DISCOUNT_SOURCE)

        first_call = str(mock_llm.call_args_list[0])
        assert "Cyclomatic complexity" in first_call or "complexity" in first_call.lower()


class TestCacheIntegration:
    """Cache: second identical run returns cache hit without LLM calls."""

    def test_cache_hit_on_second_run(self):
        pipeline = Pipeline(
            api_key="test-key",
            use_docker=False,
            max_feedback_loops=1,
            use_cache=True,
        )
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result1 = pipeline.run_from_source(DISCOUNT_SOURCE)

        # Second run — same source, should be cache hit, zero LLM calls
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm2:
            result2 = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert mock_llm2.call_count == 0, "Cache hit should make 0 LLM calls"
        assert result2.cache_hit is True

    def test_cache_hit_preserves_test_code(self):
        pipeline = Pipeline(
            api_key="test-key",
            use_docker=False,
            use_cache=True,
        )
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result1 = pipeline.run_from_source(DISCOUNT_SOURCE)

        with patch.object(pipeline._agent._client.messages, "create"):
            result2 = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result2.generated_test is not None
        assert result2.generated_test.test_code is not None
        assert "def test_" in result2.generated_test.test_code

    def test_cache_hit_preserves_test_cases(self):
        pipeline = Pipeline(
            api_key="test-key",
            use_docker=False,
            use_cache=True,
        )
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result1 = pipeline.run_from_source(DISCOUNT_SOURCE)
        original_count = len(result1.agent_result.test_cases)

        with patch.object(pipeline._agent._client.messages, "create"):
            result2 = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result2.agent_result is not None
        assert len(result2.agent_result.test_cases) == original_count

    def test_cache_hit_preserves_complexity(self):
        pipeline = Pipeline(
            api_key="test-key",
            use_docker=False,
            use_cache=True,
        )
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result1 = pipeline.run_from_source(DISCOUNT_SOURCE)
        original_cc = result1.function_info.complexity.cyclomatic_complexity

        with patch.object(pipeline._agent._client.messages, "create"):
            result2 = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert result2.function_info is not None
        assert result2.function_info.complexity is not None
        assert result2.function_info.complexity.cyclomatic_complexity == original_cc

    def test_different_source_not_cached(self):
        """Different source code must NOT return a cached result from another source."""
        from backend.cache import ResultCache
        cache = ResultCache()
        cache.clear()   # ensure clean state before this test

        pipeline = Pipeline(
            api_key="test-key",
            use_docker=False,
            use_cache=True,
        )
        other_source = "def foo(x): return x * 99"  # unique source unlikely to be cached
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            pipeline.run_from_source(DISCOUNT_SOURCE)

        with patch.object(pipeline._agent._client.messages, "create") as mock_llm2:
            mock_llm2.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            result2 = pipeline.run_from_source(other_source)

        assert mock_llm2.call_count == 2, "Different source must hit LLM, not serve cached result"
        assert result2.cache_hit is False

    def test_no_cache_mode_never_caches(self):
        """use_cache=False must never write or read from cache."""
        pipeline = make_pipeline()   # use_cache=False
        with patch.object(pipeline._agent._client.messages, "create") as mock_llm:
            mock_llm.side_effect = [_mock_response(MOCK_REASONING), _mock_response(MOCK_CODE),
                                    _mock_response(MOCK_REASONING), _mock_response(MOCK_CODE)]
            pipeline.run_from_source(DISCOUNT_SOURCE)
            result2 = pipeline.run_from_source(DISCOUNT_SOURCE)

        assert mock_llm.call_count == 4, "No-cache mode must call LLM every time"
        assert result2.cache_hit is False


class TestGitHubFetcher:
    """GitHub URL fetching — unit tests that don't hit the network."""

    def test_blob_url_converted_to_raw(self):
        from backend.parser.github_fetcher import GitHubFetcher
        fetcher = GitHubFetcher()
        raw_url, path = fetcher._to_raw_url(
            "https://github.com/user/repo/blob/main/src/utils.py"
        )
        assert raw_url == "https://raw.githubusercontent.com/user/repo/main/src/utils.py"
        assert path == "src/utils.py"

    def test_raw_url_unchanged(self):
        from backend.parser.github_fetcher import GitHubFetcher
        fetcher = GitHubFetcher()
        raw_url, _ = fetcher._to_raw_url(
            "https://raw.githubusercontent.com/user/repo/main/utils.py"
        )
        assert "raw.githubusercontent.com" in raw_url

    def test_invalid_url_returns_empty(self):
        from backend.parser.github_fetcher import GitHubFetcher
        fetcher = GitHubFetcher()
        raw_url, path = fetcher._to_raw_url("https://example.com/not-github")
        assert raw_url == ""

    def test_is_github_url_detects_github(self):
        from backend.parser.github_fetcher import GitHubFetcher
        assert GitHubFetcher.is_github_url("https://github.com/user/repo/blob/main/f.py")
        assert GitHubFetcher.is_github_url("https://raw.githubusercontent.com/user/repo/main/f.py")
        assert not GitHubFetcher.is_github_url("https://example.com/file.py")

    def test_fetch_404_returns_failure(self):
        from backend.parser.github_fetcher import GitHubFetcher
        import httpx

        fetcher = GitHubFetcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"

        with patch("httpx.Client.get", return_value=mock_resp):
            # Use a valid URL format so _to_raw_url succeeds
            with patch.object(fetcher, "_to_raw_url", return_value=("https://raw.githubusercontent.com/u/r/main/f.py", "f.py")):
                with patch("httpx.get", return_value=mock_resp):
                    result = fetcher.fetch("https://github.com/user/repo/blob/main/f.py")

        assert result.success is False
        assert "404" in result.error

    def test_pipeline_rejects_bad_github_url(self):
        """Pipeline.run_from_url with bad URL returns failed result."""
        pipeline = make_pipeline()
        with patch("backend.parser.github_fetcher.GitHubFetcher.fetch") as mock_fetch:
            mock_fetch.return_value = MagicMock(
                success=False,
                error="HTTP 404",
            )
            result = pipeline.run_from_url("https://github.com/fake/repo/blob/main/f.py")

        assert result.status == "failed"
        assert "GitHub fetch failed" in result.error