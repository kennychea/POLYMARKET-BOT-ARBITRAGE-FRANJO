"""Unit tests for core.calibration module."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.calibration import (
    apply_calibration_adjustment,
    get_calibration_report,
    is_calibrated,
)
from infra.types import CalibrationBucket


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _bucket(
    low: float = 0.0,
    high: float = 1.0,
    predicted: float = 0.5,
    actual: float = 0.5,
    count: int = 20,
    error: float | None = None,
) -> CalibrationBucket:
    """Shorthand to build a CalibrationBucket with sensible defaults."""
    if error is None:
        error = abs(predicted - actual)
    return CalibrationBucket(
        bucket_low=low,
        bucket_high=high,
        predicted_prob=predicted,
        actual_win_rate=actual,
        count=count,
        error=error,
    )


@pytest.fixture()
def standard_buckets() -> list[CalibrationBucket]:
    """Five evenly-spaced buckets covering [0, 1)."""
    return [
        _bucket(low=0.0, high=0.2, predicted=0.10, actual=0.12, count=15),
        _bucket(low=0.2, high=0.4, predicted=0.30, actual=0.28, count=20),
        _bucket(low=0.4, high=0.6, predicted=0.50, actual=0.55, count=25),
        _bucket(low=0.6, high=0.8, predicted=0.65, actual=0.80, count=30),
        _bucket(low=0.8, high=1.0, predicted=0.85, actual=0.82, count=12),
    ]


# ===================================================================
# apply_calibration_adjustment
# ===================================================================

class TestApplyCalibrationAdjustment:
    """Tests for apply_calibration_adjustment."""

    def test_adjustment_with_sufficient_samples(
        self, standard_buckets: list[CalibrationBucket]
    ) -> None:
        """Bucket 0.6-0.8 has actual=0.80, predicted=0.65 → +0.15 adjustment."""
        result = apply_calibration_adjustment(0.7, standard_buckets)
        # 0.7 + (0.80 - 0.65) = 0.85
        assert result == pytest.approx(0.85)

    def test_no_adjustment_when_low_samples(self) -> None:
        """Bucket with < 10 samples → return raw_prob unchanged."""
        buckets = [_bucket(low=0.0, high=1.0, predicted=0.5, actual=0.9, count=5)]
        assert apply_calibration_adjustment(0.5, buckets) == 0.5

    def test_clamp_low_at_001(self) -> None:
        """Extreme negative adjustment → clamp to 0.01."""
        buckets = [_bucket(low=0.0, high=1.0, predicted=0.8, actual=0.0, count=20)]
        # 0.1 + (0.0 - 0.8) = -0.7 → clamped to 0.01
        result = apply_calibration_adjustment(0.1, buckets)
        assert result == pytest.approx(0.01)

    def test_clamp_high_at_099(self) -> None:
        """Extreme positive adjustment → clamp to 0.99."""
        buckets = [_bucket(low=0.0, high=1.0, predicted=0.1, actual=0.99, count=20)]
        # 0.95 + (0.99 - 0.1) = 1.84 → clamped to 0.99
        result = apply_calibration_adjustment(0.95, buckets)
        assert result == pytest.approx(0.99)

    def test_empty_buckets_returns_raw(self) -> None:
        """Empty bucket list → return raw_prob unchanged."""
        assert apply_calibration_adjustment(0.42, []) == 0.42

    def test_boundary_prob_zero(self, standard_buckets: list[CalibrationBucket]) -> None:
        """raw_prob=0.0 falls in first bucket [0.0, 0.2)."""
        result = apply_calibration_adjustment(0.0, standard_buckets)
        # 0.0 + (0.12 - 0.10) = 0.02
        assert result == pytest.approx(0.02)

    def test_boundary_prob_high(self, standard_buckets: list[CalibrationBucket]) -> None:
        """raw_prob=0.95 falls in last bucket [0.8, 1.0)."""
        result = apply_calibration_adjustment(0.95, standard_buckets)
        # 0.95 + (0.82 - 0.85) = 0.92
        assert result == pytest.approx(0.92)

    def test_prob_at_exact_one_no_bucket(
        self, standard_buckets: list[CalibrationBucket]
    ) -> None:
        """raw_prob=1.0 doesn't match any half-open bucket → raw returned."""
        assert apply_calibration_adjustment(1.0, standard_buckets) == 1.0


# ===================================================================
# is_calibrated
# ===================================================================

class TestIsCalibrated:
    """Tests for is_calibrated."""

    def test_all_calibrated(self) -> None:
        """All buckets with error ≤ 0.08 → True."""
        buckets = [
            _bucket(error=0.02, count=20),
            _bucket(error=0.05, count=15),
            _bucket(error=0.08, count=30),
        ]
        assert is_calibrated(buckets) is True

    def test_one_bucket_miscalibrated(self) -> None:
        """One bucket with error > 0.08 → False."""
        buckets = [
            _bucket(error=0.03, count=20),
            _bucket(error=0.12, count=15),
        ]
        assert is_calibrated(buckets) is False

    def test_no_qualified_buckets(self) -> None:
        """No bucket with ≥ 10 samples → False (not enough data)."""
        buckets = [
            _bucket(error=0.01, count=3),
            _bucket(error=0.02, count=7),
        ]
        assert is_calibrated(buckets) is False

    def test_custom_max_error(self) -> None:
        """max_error=0.10 makes a 0.09-error bucket acceptable."""
        buckets = [_bucket(error=0.09, count=20)]
        assert is_calibrated(buckets, max_error=0.10) is True
        assert is_calibrated(buckets, max_error=0.08) is False

    def test_empty_list(self) -> None:
        """Empty list → False."""
        assert is_calibrated([]) is False


# ===================================================================
# get_calibration_report
# ===================================================================

class TestGetCalibrationReport:
    """Tests for get_calibration_report (DB always mocked)."""

    @patch("core.calibration.db.compute_calibration")
    def test_report_structure(self, mock_compute) -> None:
        """Returned dict has expected top-level keys."""
        mock_compute.return_value = [
            _bucket(low=0.0, high=0.5, predicted=0.25, actual=0.30, count=20, error=0.05),
            _bucket(low=0.5, high=1.0, predicted=0.75, actual=0.70, count=15, error=0.05),
        ]
        report = get_calibration_report()
        assert set(report.keys()) == {"buckets", "is_calibrated", "total_resolved", "worst_bucket"}
        assert isinstance(report["buckets"], list)
        assert len(report["buckets"]) == 2

    @patch("core.calibration.db.compute_calibration")
    def test_worst_bucket_is_correct(self, mock_compute) -> None:
        """worst_bucket should point to the bucket with the highest error."""
        mock_compute.return_value = [
            _bucket(low=0.0, high=0.5, predicted=0.25, actual=0.30, count=20, error=0.05),
            _bucket(low=0.5, high=1.0, predicted=0.75, actual=0.55, count=18, error=0.20),
        ]
        report = get_calibration_report()
        worst = report["worst_bucket"]
        assert worst["range"] == "0.5-1.0"
        assert worst["error"] == 0.2
        assert worst["samples"] == 18

    @patch("core.calibration.db.compute_calibration")
    def test_total_resolved_is_sum_of_counts(self, mock_compute) -> None:
        """total_resolved = sum of all bucket counts."""
        mock_compute.return_value = [
            _bucket(count=10),
            _bucket(count=25),
            _bucket(count=7),
        ]
        report = get_calibration_report()
        assert report["total_resolved"] == 42
