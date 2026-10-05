"""Pure financial math: Decimal in, Decimal out. No database, no HTTP.

Precision policy (also in README):
- Inputs are exact Decimals from NUMERIC columns; intermediates are NEVER
  rounded — only the presentation boundary quantizes.
- Money results quantize to 2dp; percentages to 2dp; both ROUND_HALF_UP.
- Zero denominators never divide: callers get (None, "undefined", reason).
- No float appears anywhere on this path (asserted in tests).
"""

from decimal import Decimal, ROUND_HALF_UP

MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.01")
_HUNDRED = Decimal("100")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def quantize_percent(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)


def growth_percent(
    current: Decimal, previous: Decimal
) -> tuple[Decimal | None, str, str | None]:
    """((current - previous) / previous) * 100. previous == 0 → undefined."""
    if previous == 0:
        return None, "undefined", "previous value is zero; growth is not computable"
    return quantize_percent((current - previous) / previous * _HUNDRED), "ok", None


def variance_percent(
    current: Decimal, comparison: Decimal
) -> tuple[Decimal | None, str, str | None]:
    """Percent change vs a comparison value; zero comparison → undefined."""
    if comparison == 0:
        return (
            None,
            "undefined",
            "comparison value is zero; percent variance is not computable",
        )
    return quantize_percent((current - comparison) / comparison * _HUNDRED), "ok", None


def margin_percent(
    revenue: Decimal, expense: Decimal
) -> tuple[Decimal | None, str, str | None]:
    """((revenue - expense) / revenue) * 100. Zero revenue → undefined."""
    if revenue == 0:
        return None, "undefined", "revenue is zero; margin is not computable"
    return quantize_percent((revenue - expense) / revenue * _HUNDRED), "ok", None
