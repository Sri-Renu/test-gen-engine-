# Mutation Testing Report — calculate_discount

**Function:** `calculate_discount(price, discount_percent)`
**Tool:** mutmut 3.6.0
**Date:** 2025-01-15 (benchmark run)

---

## Summary

| Stage | Score | Killed | Survived | Total Mutants |
|-------|-------|--------|----------|---------------|
| Baseline (2 tests) | 37.5% | 6 | 10 | 16 |
| After agent generation (11 tests) | **50.0%** | **8** | **8** | **16** |

The feedback loop improved the score from 37.5% → 50.0% by targeting the
two logic mutations that survived the baseline:

- `discount_percent > 100` → `discount_percent >= 100` (killed by boundary test at exactly 100)
- `discount_percent > 100` → `discount_percent > 101` (killed by test at 101)

---

## Remaining 8 Survivors — Why They Survive (And Why That's Correct)

All 8 surviving mutants are **string content mutations inside ValueError messages**:

```
Mutant #3:  raise ValueError("Discount cannot exceed 100 percent")
         →  raise ValueError(None)

Mutant #4:  raise ValueError("Discount cannot exceed 100 percent")
         →  raise ValueError("XXDiscount cannot exceed 100 percentXX")

Mutant #5:  raise ValueError("Discount cannot exceed 100 percent")
         →  raise ValueError("discount cannot exceed 100 percent")   # lowercase

Mutant #6:  raise ValueError("Discount cannot exceed 100 percent")
         →  raise ValueError("DISCOUNT CANNOT EXCEED 100 PERCENT")   # uppercase

Mutants #9-12: Same pattern on the second ValueError message
```

**These are intentionally not killed.** Asserting on exception message text
(`assert "Discount cannot exceed" in str(exc)`) is a well-known anti-pattern:
it makes tests brittle against legitimate refactoring of error messages,
and adds zero protection against real logic bugs.

The correct interpretation: **50% is the realistic ceiling for this function.**
The 8 surviving mutants are cosmetic, not logical. Every logic mutation is killed.

---

## What Each Killed Mutant Means

| Mutant | Change | Killed By |
|--------|--------|-----------|
| #1 | `> 100` → `>= 100` | `test_boundary_exactly_100_does_not_raise` |
| #2 | `> 100` → `> 101` | `test_boundary_101_is_invalid` |
| #7 | `< 0` → `<= 0` | `test_boundary_zero_discount_returns_full_price` |
| #8 | `< 0` → `< -1` | `test_boundary_negative_1_raises` |
| #13 | arithmetic sign flip | `test_happy_path_ten_percent_off_100` |
| #14 | coefficient removed | `test_happy_path_twenty_five_percent_off_200` |
| #15 | division → multiplication | `test_invariant_zero_price_always_returns_zero` |
| #16 | subtraction → addition | `test_invariant_positive_discount_reduces_price` |

---

## Interview Answer

> **"What mutation score did it achieve?"**

50% on `calculate_discount` with 11 generated tests killing all 8 logic
mutations. The remaining 8 survivors are string content mutations inside
exception messages — asserting on those is an anti-pattern. Every meaningful
logic mutation is killed.

> **"Did the feedback loop actually improve the score?"**

Yes. Baseline (2 tests, no agent) scored 37.5%. After the agent's first pass
(11 tests): 50.0%. The feedback loop specifically targeted and killed the two
operator boundary mutations (`> 100` → `>= 100` and `> 100` → `> 101`) by
generating `test_boundary_exactly_100_does_not_raise` and
`test_boundary_101_is_invalid`.