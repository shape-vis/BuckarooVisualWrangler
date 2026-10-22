"""Shared benchmark provenance checks for profiler experiments."""

from __future__ import annotations

from typing import Any

import pandas as pd


APPROVED_REVIEW_STATUSES = {"approved", "human_reviewed", "reviewed", "verified"}


def _is_yes(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"yes", "true", "1"}


def benchmark_quality(labels: pd.DataFrame) -> dict[str, Any]:
    """Describe whether a label file supports human accuracy and key recall."""
    total = int(len(labels))
    if "review_status" in labels:
        statuses = labels["review_status"].fillna("").astype(str).str.strip().str.lower()
    else:
        statuses = pd.Series([""] * total, index=labels.index, dtype="object")
    reviewed_mask = statuses.isin(APPROVED_REVIEW_STATUSES)

    key_mask = labels.apply(
        lambda row: _is_yes(row.get("is_primary_key"))
        or _is_yes(row.get("corrected_is_primary_key")),
        axis=1,
    ) if total else pd.Series(dtype="bool")

    reviewed_rows = int(reviewed_mask.sum())
    positive_key_rows = int(key_mask.sum())
    fully_reviewed = bool(total > 0 and reviewed_rows == total)
    return {
        "label_rows": total,
        "human_reviewed_rows": reviewed_rows,
        "needs_review_rows": total - reviewed_rows,
        "benchmark_is_fully_human_reviewed": fully_reviewed,
        "benchmark_label_source": (
            "human_reviewed_ground_truth"
            if fully_reviewed
            else "provisional_ai_generated_labels_pending_human_review"
        ),
        "positive_primary_key_rows": positive_key_rows,
        "benchmark_supports_key_recall": positive_key_rows > 0,
    }


def accuracy_output(matches: pd.Series, quality: dict[str, Any]) -> dict[str, float | None]:
    """Use honest metric names based on the benchmark's review provenance."""
    agreement = round(float(matches.mean()), 6) if not matches.empty else None
    return {
        "manual_accuracy": agreement if quality["benchmark_is_fully_human_reviewed"] else None,
        "provisional_label_agreement": (
            None if quality["benchmark_is_fully_human_reviewed"] else agreement
        ),
    }
