"""Calculation math unit tests: pure Decimal, zero-denominators, quantization."""

from decimal import Decimal

from app.services import calc_math


def _is_decimal(value) -> bool:  # type: ignore[no-untyped-def]
    return isinstance(value, Decimal) and not isinstance(value, float)


def test_growth_exact() -> None:
    value, status, reason = calc_math.growth_percent(Decimal("1200"), Decimal("1000"))
    assert (value, status, reason) == (Decimal("20.00"), "ok", None)
    assert _is_decimal(value)


def test_growth_zero_previous_is_undefined() -> None:
    value, status, reason = calc_math.growth_percent(Decimal("100"), Decimal("0"))
    assert value is None and status == "undefined" and reason


def test_variance_and_percent() -> None:
    percent, status, _ = calc_math.variance_percent(Decimal("1200"), Decimal("1000"))
    assert (percent, status) == (Decimal("20.00"), "ok")
    percent, status, reason = calc_math.variance_percent(Decimal("5"), Decimal("0"))
    assert percent is None and status == "undefined" and reason


def test_margin_exact_and_zero_revenue() -> None:
    value, status, _ = calc_math.margin_percent(Decimal("1200"), Decimal("300"))
    assert (value, status) == (Decimal("75.00"), "ok")
    value, status, reason = calc_math.margin_percent(Decimal("0"), Decimal("300"))
    assert value is None and status == "undefined" and reason


def test_quantization_half_up_only_at_boundary() -> None:
    # 866.666... must become 866.67, never via an intermediate float.
    assert calc_math.quantize_money(Decimal(2600) / Decimal(3)) == Decimal("866.67")
    assert calc_math.quantize_money(Decimal("2.675")) == Decimal("2.68")
    assert calc_math.quantize_percent(Decimal("33.335")) == Decimal("33.34")


def test_no_float_anywhere() -> None:
    outputs = [
        calc_math.growth_percent(Decimal("1"), Decimal("3"))[0],
        calc_math.variance_percent(Decimal("1"), Decimal("3"))[0],
        calc_math.margin_percent(Decimal("2"), Decimal("3"))[0],
        calc_math.quantize_money(Decimal("1.005")),
    ]
    for value in outputs:
        assert _is_decimal(value)
