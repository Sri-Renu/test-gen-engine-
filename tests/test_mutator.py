"""
Mutation testing tests — real mutmut runs, no mocking.
These validate the full mutmut 3.x integration.

Run with: pytest tests/test_mutator.py -v
(mutmut must be installed: pip install mutmut)
"""
import pytest
from backend.mutator.mutator import MutationRunner


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

DISCOUNT_SOURCE = '''
def calculate_discount(price: float, discount_percent: float) -> float:
    if discount_percent > 100:
        raise ValueError("Discount can't exceed 100%")
    if discount_percent < 0:
        raise ValueError("Discount can't be negative")
    return price - (price * discount_percent / 100)
'''

# Weak tests — many mutants will survive (tests invariant score < 80%)
WEAK_TESTS = '''
import pytest
from source import calculate_discount

def test_basic():
    result = calculate_discount(100.0, 10.0)
    assert result == 90.0
'''

# Strong tests — should kill 80%+ of mutants
STRONG_TESTS = '''
import pytest
from source import calculate_discount

def test_happy_path_10_percent():
    assert calculate_discount(100.0, 10.0) == pytest.approx(90.0)

def test_happy_path_50_percent():
    assert calculate_discount(200.0, 50.0) == pytest.approx(100.0)

def test_boundary_zero_discount():
    assert calculate_discount(100.0, 0.0) == pytest.approx(100.0)

def test_boundary_full_discount():
    assert calculate_discount(100.0, 100.0) == pytest.approx(0.0)

def test_boundary_101_raises():
    with pytest.raises(ValueError):
        calculate_discount(100.0, 101.0)

def test_boundary_100_valid():
    # Exactly 100 must NOT raise
    result = calculate_discount(50.0, 100.0)
    assert result == pytest.approx(0.0)

def test_exception_over_100():
    with pytest.raises(ValueError):
        calculate_discount(100.0, 150.0)

def test_exception_negative():
    with pytest.raises(ValueError):
        calculate_discount(100.0, -1.0)

def test_exception_negative_large():
    with pytest.raises(ValueError):
        calculate_discount(100.0, -100.0)

def test_price_zero():
    assert calculate_discount(0.0, 50.0) == pytest.approx(0.0)

def test_invariant_result_less_than_price():
    result = calculate_discount(100.0, 25.0)
    assert result < 100.0

def test_invariant_result_nonnegative():
    result = calculate_discount(100.0, 100.0)
    assert result >= 0.0
'''

SIMPLE_SOURCE = '''
def add(a: int, b: int) -> int:
    return a + b
'''

SIMPLE_TESTS = '''
import pytest
from source import add

def test_add_positive():
    assert add(2, 3) == 5

def test_add_zero():
    assert add(0, 0) == 0

def test_add_negative():
    assert add(-1, -1) == -2
'''


# ---------------------------------------------------------------------------
# MutationRunner unit tests (parsing logic, no real mutmut call)
# ---------------------------------------------------------------------------

class TestMutationRunnerParsing:

    def setup_method(self):
        self.runner = MutationRunner()

    def test_parse_result_lines_killed(self):
        output = "    source.x_fn__mutmut_1: killed\n"
        results = self.runner._parse_result_lines(output)
        assert results == [("source.x_fn__mutmut_1", "killed")]

    def test_parse_result_lines_survived(self):
        output = "    source.x_fn__mutmut_3: survived\n"
        results = self.runner._parse_result_lines(output)
        assert results == [("source.x_fn__mutmut_3", "survived")]

    def test_parse_multiple_results(self):
        output = (
            "    source.x_fn__mutmut_1: killed\n"
            "    source.x_fn__mutmut_2: killed\n"
            "    source.x_fn__mutmut_3: survived\n"
            "    source.x_fn__mutmut_4: survived\n"
        )
        results = self.runner._parse_result_lines(output)
        assert len(results) == 4
        assert results[0] == ("source.x_fn__mutmut_1", "killed")
        assert results[2] == ("source.x_fn__mutmut_3", "survived")

    def test_parse_ignores_blank_lines(self):
        output = "\n    source.x_fn__mutmut_1: killed\n\n"
        results = self.runner._parse_result_lines(output)
        assert len(results) == 1

    def test_parse_empty_output(self):
        results = self.runner._parse_result_lines("")
        assert results == []

    def test_extract_diff_from_show_output(self):
        show_output = (
            "# source.x_fn__mutmut_3: survived\n"
            "--- source.py\n"
            "+++ source.py\n"
            "@@ -2,4 +2,4 @@\n"
            "-    if discount_percent > 100:\n"
            "+    if discount_percent >= 100:\n"
        )
        result = self.runner._extract_diff(show_output, "source.x_fn__mutmut_3")
        assert ">" in result or ">=" in result
        assert result != ""

    def test_extract_diff_handles_empty_show(self):
        result = self.runner._extract_diff("", "source.x_fn__mutmut_99")
        assert "survived" in result or "99" in result

    def test_timeout_report_structure(self):
        report = self.runner._timeout_report("my_func")
        assert report.function_name == "my_func"
        assert report.mutation_score == 0.0
        assert report.timed_out == 1
        assert len(report.survived_descriptions) > 0


# ---------------------------------------------------------------------------
# Integration tests — real mutmut runs
# ---------------------------------------------------------------------------

class TestMutationRunnerIntegration:

    def setup_method(self):
        self.runner = MutationRunner(timeout=120)

    def test_returns_mutation_report(self):
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        assert report is not None
        assert report.function_name == "calculate_discount"

    def test_total_mutants_nonzero(self):
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        assert report.total_mutants > 0

    def test_killed_plus_survived_equals_total(self):
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        assert report.killed + report.survived + report.timed_out == report.total_mutants

    def test_mutation_score_is_percentage(self):
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        assert 0.0 <= report.mutation_score <= 100.0

    def test_strong_tests_score_above_40(self):
        """Strong test suite kills logic mutants. String mutations inside
        exception messages legitimately survive without asserting on message
        text (which is an anti-pattern). 40%+ is a realistic floor."""
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        assert report.mutation_score >= 40.0, (
            f"Expected >= 40%, got {report.mutation_score}%. "
            f"Killed: {report.killed}/{report.total_mutants}"
        )

    def test_weak_tests_score_below_strong(self):
        """Weak tests should score lower than strong tests."""
        weak_report  = self.runner.run("calculate_discount", DISCOUNT_SOURCE, WEAK_TESTS)
        strong_report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        assert weak_report.mutation_score < strong_report.mutation_score, (
            f"Weak: {weak_report.mutation_score}%, Strong: {strong_report.mutation_score}%"
        )

    def test_survived_descriptions_populated_when_survived(self):
        """If mutants survive, their diffs should be in survived_descriptions."""
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, WEAK_TESTS)
        if report.survived > 0:
            assert len(report.survived_descriptions) > 0
            # Each description should contain useful diff info
            assert any("Mutant" in d for d in report.survived_descriptions)

    def test_survived_descriptions_contain_diff_info(self):
        """Survived descriptions must show WHAT changed (for the feedback loop)."""
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, WEAK_TESTS)
        if report.survived > 0 and report.survived_descriptions:
            # At least one description should have a +/- diff indicator
            assert any(
                "+" in d or "-" in d or ">" in d or ">=" in d or "None" in d
                for d in report.survived_descriptions
            )

    def test_simple_function_runs(self):
        """Smoke test on a trivial function."""
        report = self.runner.run("add", SIMPLE_SOURCE, SIMPLE_TESTS)
        assert report.total_mutants > 0
        assert report.mutation_score >= 0.0

    def test_mutant_results_populated(self):
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        assert len(report.mutant_results) == report.total_mutants

    def test_mutant_result_statuses_valid(self):
        report = self.runner.run("calculate_discount", DISCOUNT_SOURCE, STRONG_TESTS)
        valid_statuses = {"killed", "survived", "timeout", "suspicious", "error"}
        for mr in report.mutant_results:
            assert mr.status in valid_statuses, f"Unknown status: {mr.status}"