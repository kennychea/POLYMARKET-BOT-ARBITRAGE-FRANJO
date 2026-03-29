"""Calibration module — adjusts scorer probabilities based on historical accuracy."""
from __future__ import annotations

import logging

import infra.db as db
from infra.types import CalibrationBucket

logger = logging.getLogger(__name__)

MIN_BUCKET_SAMPLES = 10


def apply_calibration_adjustment(
    raw_prob: float, buckets: list[CalibrationBucket]
) -> float:
    """Adjust raw probability using historical calibration data."""
    for bucket in buckets:
        if bucket.bucket_low <= raw_prob < bucket.bucket_high:
            if bucket.count >= MIN_BUCKET_SAMPLES:
                adjusted = raw_prob + (bucket.actual_win_rate - bucket.predicted_prob)
                result = max(0.01, min(0.99, adjusted))
                logger.debug(
                    "calibration_applied",
                    extra={
                        "raw": raw_prob,
                        "adjusted": result,
                        "bucket": f"{bucket.bucket_low:.1f}-{bucket.bucket_high:.1f}",
                    },
                )
                return result
            logger.debug(
                "calibration_skipped_low_samples",
                extra={"raw": raw_prob, "samples": bucket.count},
            )
            return raw_prob
    return raw_prob


def is_calibrated(
    buckets: list[CalibrationBucket], max_error: float = 0.08
) -> bool:
    """Return True if all buckets with enough samples have acceptable error."""
    qualified = [b for b in buckets if b.count >= MIN_BUCKET_SAMPLES]
    if not qualified:
        return False
    return all(b.error <= max_error for b in qualified)


def get_calibration_report() -> dict[str, object]:
    """Build a calibration report from resolved trades."""
    buckets = db.compute_calibration()

    bucket_dicts = [
        {
            "range": f"{b.bucket_low:.1f}-{b.bucket_high:.1f}",
            "predicted": round(b.predicted_prob, 3),
            "actual": round(b.actual_win_rate, 3),
            "error": round(b.error, 3),
            "samples": b.count,
        }
        for b in buckets
    ]

    total_resolved = sum(b.count for b in buckets)
    worst = max(buckets, key=lambda b: b.error) if buckets else None

    report: dict[str, object] = {
        "buckets": bucket_dicts,
        "is_calibrated": is_calibrated(buckets),
        "total_resolved": total_resolved,
        "worst_bucket": (
            {
                "range": f"{worst.bucket_low:.1f}-{worst.bucket_high:.1f}",
                "error": round(worst.error, 3),
                "samples": worst.count,
            }
            if worst
            else None
        ),
    }

    logger.info(
        "calibration_report",
        extra={
            "total_resolved": total_resolved,
            "is_calibrated": report["is_calibrated"],
        },
    )
    return report
