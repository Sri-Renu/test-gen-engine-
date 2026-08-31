"""
Auto-generated tests for: calculate_discount
Generated:   2025-01-15 (benchmark run)
Test cases:  11
Categories:  boundary, exception, happy_path, invariant

Agent reasoning:
    calculate_discount has two guarded raise paths (> 100, < 0) and pure
    arithmetic on the return. Boundary conditions at exactly 0 and 100 are
    critical — operator choice (> vs >=) determines whether the boundary
    value is valid. String content of ValueError messages is deliberately
    not asserted; that is an anti-pattern that makes tests brittle.
"""

import pytest
from calculate_discount import calculate_discount


# ── Happy path ────────────────────────────────────────────────────────

# Core arithmetic must be correct for a typical discount
def test_happy_path_ten_percent_off_100():
    assert calculate_discount(100.0, 10.0) == pytest.approx(90.0)

# Non-trivial values to catch coefficient errors
def test_happy_path_twenty_five_percent_off_200():
    assert calculate_discount(200.0, 25.0) == pytest.approx(150.0)


# ── Boundary ──────────────────────────────────────────────────────────

# Lower boundary: 0% discount must return the full price unchanged
def test_boundary_zero_discount_returns_full_price():
    assert calculate_discount(100.0, 0.0) == pytest.approx(100.0)

# Upper boundary: exactly 100% must be valid (not raise) and return zero
def test_boundary_100_percent_is_valid_and_returns_zero():
    assert calculate_discount(100.0, 100.0) == pytest.approx(0.0)

# This catches the > vs >= mutation: 100 must NOT raise
def test_boundary_exactly_100_does_not_raise():
    result = calculate_discount(50.0, 100.0)
    assert result == pytest.approx(0.0)

# This catches the > vs > 101 mutation: 101 MUST raise
def test_boundary_101_is_invalid():
    with pytest.raises(ValueError):
        calculate_discount(100.0, 101.0)

# Lower guard: -1 must raise
def test_boundary_negative_1_raises():
    with pytest.raises(ValueError):
        calculate_discount(100.0, -1.0)


# ── Exception ─────────────────────────────────────────────────────────

# Large invalid value — ensures the guard catches more than just 101
def test_exception_150_raises():
    with pytest.raises(ValueError):
        calculate_discount(100.0, 150.0)

# Large negative — ensures the lower guard works
def test_exception_large_negative_raises():
    with pytest.raises(ValueError):
        calculate_discount(100.0, -99.0)


# ── Invariant ─────────────────────────────────────────────────────────

# A positive discount must always reduce the price
def test_invariant_positive_discount_reduces_price():
    result = calculate_discount(500.0, 30.0)
    assert result < 500.0

# Zero price must always yield zero regardless of discount
def test_invariant_zero_price_always_returns_zero():
    assert calculate_discount(0.0, 50.0) == pytest.approx(0.0)