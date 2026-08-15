"""Persist how much of each uploaded dataset Buckaroo has actually inspected."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


METADATA_TABLE = "buckaroo_dataset_processing_metadata"


def ensure_metadata_table(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {METADATA_TABLE} (
                table_name TEXT PRIMARY KEY,
                total_rows BIGINT NOT NULL,
                detector_rows BIGINT NOT NULL,
                detector_is_complete BOOLEAN NOT NULL,
                detector_sampling_method TEXT NOT NULL,
                detector_sample_seed BIGINT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))


def save_dataset_processing_metadata(
    engine,
    *,
    table_name: str,
    total_rows: int,
    detector_rows: int,
    detector_is_complete: bool,
    detector_sampling_method: str,
    detector_sample_seed: int | None,
) -> None:
    """Insert or replace the detector coverage record for one dataset version."""
    ensure_metadata_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(f"""
                INSERT INTO {METADATA_TABLE} (
                    table_name,
                    total_rows,
                    detector_rows,
                    detector_is_complete,
                    detector_sampling_method,
                    detector_sample_seed,
                    updated_at
                )
                VALUES (
                    :table_name,
                    :total_rows,
                    :detector_rows,
                    :detector_is_complete,
                    :detector_sampling_method,
                    :detector_sample_seed,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (table_name) DO UPDATE
                SET total_rows = EXCLUDED.total_rows,
                    detector_rows = EXCLUDED.detector_rows,
                    detector_is_complete = EXCLUDED.detector_is_complete,
                    detector_sampling_method = EXCLUDED.detector_sampling_method,
                    detector_sample_seed = EXCLUDED.detector_sample_seed,
                    updated_at = CURRENT_TIMESTAMP
            """),
            {
                "table_name": table_name,
                "total_rows": max(0, int(total_rows)),
                "detector_rows": max(0, int(detector_rows)),
                "detector_is_complete": bool(detector_is_complete),
                "detector_sampling_method": str(detector_sampling_method),
                "detector_sample_seed": detector_sample_seed,
            },
        )


def get_dataset_processing_metadata(engine, table_name: str) -> dict[str, Any] | None:
    """Return detector coverage, or ``None`` for tables created before metadata existed."""
    ensure_metadata_table(engine)
    with engine.connect() as connection:
        row = connection.execute(
            text(f"""
                SELECT
                    total_rows,
                    detector_rows,
                    detector_is_complete,
                    detector_sampling_method,
                    detector_sample_seed
                FROM {METADATA_TABLE}
                WHERE table_name = :table_name
            """),
            {"table_name": table_name},
        ).mappings().first()
    return dict(row) if row else None


def mark_detector_complete(engine, table_name: str, total_rows: int) -> None:
    save_dataset_processing_metadata(
        engine,
        table_name=table_name,
        total_rows=total_rows,
        detector_rows=total_rows,
        detector_is_complete=True,
        detector_sampling_method="full_dataset",
        detector_sample_seed=None,
    )
