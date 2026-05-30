"""Tests for core/weight.py — pure weight conversion functions."""

import pytest

from app.core.weight import (
    DEFAULT_TARE_GRAMS,
    fdb_to_spoolman_net,
    spoolman_to_fdb_gross,
    weight_changed,
)


class TestSpoolmanToFdbGross:
    def test_basic_conversion(self):
        result = spoolman_to_fdb_gross(800.0, 220.0)
        assert result.total_weight == pytest.approx(1020.0)
        assert result.used_default_tare is False

    def test_zero_remaining(self):
        result = spoolman_to_fdb_gross(0.0, 220.0)
        assert result.total_weight == pytest.approx(220.0)

    def test_default_tare_when_none(self):
        result = spoolman_to_fdb_gross(800.0, None)
        assert result.total_weight == pytest.approx(800.0 + DEFAULT_TARE_GRAMS)
        assert result.used_default_tare is True

    def test_explicit_zero_tare(self):
        result = spoolman_to_fdb_gross(500.0, 0.0)
        assert result.total_weight == pytest.approx(500.0)
        assert result.used_default_tare is False


class TestFdbToSpoolmanNet:
    def test_basic_conversion(self):
        result = fdb_to_spoolman_net(1020.0, 220.0, 0.0)
        assert result.remaining_weight == pytest.approx(800.0)
        assert result.used_default_tare is False

    def test_with_usage(self):
        result = fdb_to_spoolman_net(1020.0, 220.0, 100.0)
        assert result.remaining_weight == pytest.approx(700.0)

    def test_default_tare_when_none(self):
        result = fdb_to_spoolman_net(1000.0, None, 0.0)
        assert result.remaining_weight == pytest.approx(1000.0 - DEFAULT_TARE_GRAMS)
        assert result.used_default_tare is True

    def test_clamps_at_zero(self):
        # Over-usage should not produce negative remaining weight
        result = fdb_to_spoolman_net(220.0, 220.0, 500.0)
        assert result.remaining_weight == pytest.approx(0.0)

    def test_roundtrip(self):
        # gross → net → gross should recover the original net weight
        gross = spoolman_to_fdb_gross(750.0, 200.0).total_weight
        net = fdb_to_spoolman_net(gross, 200.0, 0.0).remaining_weight
        assert net == pytest.approx(750.0)


class TestWeightPrecision:
    def test_spoolman_to_fdb_rounds_to_default_2(self):
        result = spoolman_to_fdb_gross(539.4936014320408, None)
        assert result.total_weight == pytest.approx(739.49)

    def test_spoolman_to_fdb_rounds_to_zero(self):
        result = spoolman_to_fdb_gross(539.4936014320408, None, precision=0)
        assert result.total_weight == 739.0

    def test_spoolman_to_fdb_rounds_to_one(self):
        result = spoolman_to_fdb_gross(539.4936014320408, None, precision=1)
        assert result.total_weight == pytest.approx(739.5)

    def test_fdb_to_spoolman_rounds_to_default_2(self):
        result = fdb_to_spoolman_net(739.4936014320408, None)
        assert result.remaining_weight == pytest.approx(539.49)

    def test_fdb_to_spoolman_rounds_to_zero(self):
        result = fdb_to_spoolman_net(739.4936014320408, None, precision=0)
        assert result.remaining_weight == 539.0

    def test_roundtrip_stable_at_precision_2(self):
        net_original = 750.123456
        gross = spoolman_to_fdb_gross(net_original, 200.0).total_weight
        net_back = fdb_to_spoolman_net(gross, 200.0).remaining_weight
        # round-trip at precision 2 stays within rounding error
        assert abs(net_back - round(net_original, 2)) < 0.005


class TestWeightChanged:
    def test_above_threshold(self):
        assert weight_changed(1000.0, 995.0, 2.0) is True

    def test_exactly_at_threshold(self):
        assert weight_changed(1000.0, 998.0, 2.0) is True

    def test_below_threshold(self):
        assert weight_changed(1000.0, 999.0, 2.0) is False

    def test_increase_above_threshold(self):
        assert weight_changed(990.0, 1000.0, 2.0) is True

    def test_old_none_returns_false(self):
        assert weight_changed(None, 500.0, 2.0) is False

    def test_new_none_returns_false(self):
        assert weight_changed(500.0, None, 2.0) is False

    def test_both_none_returns_false(self):
        assert weight_changed(None, None, 2.0) is False

    def test_zero_threshold(self):
        assert weight_changed(100.0, 99.99, 0.0) is True
