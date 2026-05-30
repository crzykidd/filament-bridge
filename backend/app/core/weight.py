"""Pure weight-conversion helpers — no I/O, trivially testable."""

from typing import NamedTuple

DEFAULT_TARE_GRAMS = 200.0


class GrossResult(NamedTuple):
    total_weight: float
    used_default_tare: bool


class NetResult(NamedTuple):
    remaining_weight: float
    used_default_tare: bool


def spoolman_to_fdb_gross(
    remaining_weight: float,
    spool_weight: float | None,
    precision: int = 2,
) -> GrossResult:
    """Convert Spoolman net remaining_weight → Filament DB gross totalWeight."""
    used_default = spool_weight is None
    tare = DEFAULT_TARE_GRAMS if used_default else spool_weight
    return GrossResult(total_weight=round(remaining_weight + tare, precision), used_default_tare=used_default)


def fdb_to_spoolman_net(
    total_weight: float,
    spool_weight: float | None,
    usage_grams_sum: float = 0.0,
    precision: int = 2,
) -> NetResult:
    """Convert Filament DB gross totalWeight → Spoolman net remaining_weight."""
    used_default = spool_weight is None
    tare = DEFAULT_TARE_GRAMS if used_default else spool_weight
    net = total_weight - tare - usage_grams_sum
    return NetResult(remaining_weight=round(max(net, 0.0), precision), used_default_tare=used_default)


def weight_changed(old: float | None, new: float | None, threshold: float) -> bool:
    """Return True when |old − new| ≥ threshold. Both None → False."""
    if old is None or new is None:
        return False
    return abs(old - new) >= threshold
