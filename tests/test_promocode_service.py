"""Unit tests for the pure promocode math.

The reservation / release helpers hit Postgres, so those are covered by
the bruno smoke-test pack rather than in pytest. The discount-math
function is pure and worth pinning down because off-by-one errors here
directly translate into a buyer being over- or under-charged.
"""
from __future__ import annotations

import pytest

from app.models.enums import PromocodeDiscountKind
from app.services.promocode_service import compute_discount_cents


@pytest.mark.parametrize(
    "base, value, expected",
    [
        (100_000, 10, 10_000),
        (100_000, 50, 50_000),
        (99_999, 50, 49_999),  # floor division — never rounds against the seller
        (100_000, 1, 1_000),
        (100_000, 100, 100_000),  # caller is responsible for rejecting 100%
        (0, 50, 0),  # free course → no discount
    ],
)
def test_percent_discount(base: int, value: int, expected: int) -> None:
    assert (
        compute_discount_cents(
            kind=PromocodeDiscountKind.PERCENT,
            value=value,
            base_amount_cents=base,
        )
        == expected
    )


@pytest.mark.parametrize(
    "base, value, expected",
    [
        (100_000, 25_000, 25_000),
        (100_000, 100_000, 100_000),  # exactly the price — clipped, full discount
        (100_000, 150_000, 100_000),  # over-spec — clipped to base
        (50_000, 1, 1),
        (0, 5_000, 0),
    ],
)
def test_fixed_discount(base: int, value: int, expected: int) -> None:
    assert (
        compute_discount_cents(
            kind=PromocodeDiscountKind.FIXED,
            value=value,
            base_amount_cents=base,
        )
        == expected
    )


def test_negative_base_returns_zero() -> None:
    """Defensive: a bogus negative base never produces a negative discount."""
    assert (
        compute_discount_cents(
            kind=PromocodeDiscountKind.FIXED,
            value=100,
            base_amount_cents=-1,
        )
        == 0
    )
