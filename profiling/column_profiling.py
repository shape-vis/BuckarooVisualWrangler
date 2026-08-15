"""Confidence-aware column profiling shared by Buckaroo and its experiments.

The Flask backend imports the reusable profiling API from this module. The
command-line compatibility wrapper in ``experiments/profile_dataset_shape.py``
imports the same functions, ensuring experiments and production execute one
implementation rather than drifting copies.

The optional CLI also answers table-level questions from the meta-detector
discussion:

- How many rows and columns does the dataset have?
- How many columns look numeric, categorical, or free-text?
- How much missingness is present?
- What baseline error rate do the current Buckaroo detectors produce?
- How many rows have at least one detector error?

Run examples:
    python experiments/profile_dataset_shape.py --dataset provided_datasets/adult.csv
    python experiments/profile_dataset_shape.py --multi-dataset
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any

import pandas as pd


# This module lives in profiling/, one level below the repository root.
ROOT = Path(__file__).resolve().parents[1]

# When we run this script directly, Python may not automatically know how to
# import project files like detectors/anomaly.py.  This adds the project root
# to Python's import search path.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# These are the same detector functions Buckaroo uses to find possible errors.
# We import them directly so this experiment can run without starting Flask or
# opening the web app.
from detectors.anomaly import anomaly
from detectors.common import infer_detector_config, is_missing_value
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value
from detectors.approx_cardinality import (  # noqa: E402
    DEFAULT_EXACT_LIMIT,
    DEFAULT_HLL_PRECISION,
    DistinctCountAccumulator,
    DistinctCountProfile,
    distinct_count_profile,
)
from detectors.ucc_discovery import (  # noqa: E402
    DEFAULT_UCC_MAX_ARITY,
    DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
    DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD,
    discover_ucc_candidates_in_csv,
)


# If the user runs this script without choosing a dataset, use adult.csv.
DEFAULT_DATASET = ROOT / "provided_datasets" / "adult.csv"

# If the user asks for --multi-dataset, look for CSV files in this folder.
DEFAULT_DATASET_DIR = ROOT / "provided_datasets"

# Put the result CSVs and Markdown report in this output folder.
DEFAULT_OUT_DIR = ROOT / "experiments" / "dataset_profile_outputs"


@dataclass(frozen=True)
class ProfilerFeatureFlags:
    """Feature switches used by production profiling and true ablation runs."""

    use_confidence_intervals: bool = True
    use_geography_safeguards: bool = True
    use_timestamp_safeguards: bool = True
    include_candidate_roles: bool = True
    enable_adaptive_sampling: bool = True


DEFAULT_PROFILER_FEATURES = ProfilerFeatureFlags()

# By default, inspect this many rows to decide column types and missingness.
# This is cheaper than running detectors.
DEFAULT_PROFILE_ROWS = 5000

# By default, run Buckaroo detectors on this many rows.  Detector runs are more
# expensive than simple profiling, so this can be smaller than profile rows.
DEFAULT_DETECTOR_ROWS = 2000

# How many distinct normalized values we are willing to store exactly before
# switching to HyperLogLog-style approximate counting.
DEFAULT_DISTINCT_EXACT_LIMIT = DEFAULT_EXACT_LIMIT

# Number of CSV rows processed per chunk when scanning full-file cardinality.
DEFAULT_CARDINALITY_CHUNK_ROWS = 50_000


# Column-name hints used by the explainable profiler rules.
#
# These hints are not enough by themselves.  They are combined with measured
# evidence such as numeric ratio, uniqueness, word count, and date parsing.
ID_NAME_TOKENS = {
    "id",
    "identifier",
    "case",
    "uuid",
    "guid",
    "vin",
    "zip",
    "zipcode",
    "postal",
    "ssn",
    "invoice",
    "ticket",
    "claim",
    "account",
    "unnamed",
}

LATITUDE_NAME_TOKENS = {"lat", "latitude"}

LONGITUDE_NAME_TOKENS = {"lon", "long", "lng", "longitude"}

POSTAL_NAME_TOKENS = {"postal", "postcode", "zip", "zipcode"}

AIRPORT_CODE_NAME_TOKENS = {"airport", "iata", "icao"}

COUNTRY_CODE_NAME_TOKENS = {"country"}

LOCATION_NAME_TOKENS = {
    "address",
    "borough",
    "city",
    "continent",
    "coordinate",
    "coordinates",
    "country",
    "county",
    "geography",
    "lat",
    "latitude",
    "lng",
    "locality",
    "location",
    "lon",
    "long",
    "longitude",
    "municipality",
    "place",
    "postal",
    "postcode",
    "province",
    "region",
    "state",
    "territory",
    "zip",
    "zipcode",
    "zone",
}

GEOGRAPHY_PROFILE_ROLES = {
    "airport_code",
    "country_code",
    "geographic_coordinate",
    "high_uniqueness_location_field",
    "location_name",
    "postal_code",
}

CATEGORY_CODE_NAME_TOKENS = {
    "category",
    "class",
    "code",
    "flag",
    "gender",
    "race",
    "ethnicity",
    "label",
    "level",
    "status",
    "target",
    "type",
    "ward",
    "beat",
    "iucr",
    "fbi",
}

MEASUREMENT_NAME_TOKENS = {
    "age",
    "amount",
    "balance",
    "count",
    "coordinate",
    "cost",
    "day",
    "days",
    "distance",
    "duration",
    "height",
    "hour",
    "hours",
    "income",
    "kg",
    "kilogram",
    "kilograms",
    "latitude",
    "longitude",
    "loss",
    "mean",
    "median",
    "mile",
    "miles",
    "minute",
    "minutes",
    "month",
    "months",
    "number",
    "num",
    "odometer",
    "percent",
    "percentage",
    "price",
    "quantity",
    "rate",
    "ratio",
    "salary",
    "sales",
    "score",
    "second",
    "seconds",
    "total",
    "value",
    "weight",
    "week",
    "weeks",
    "year",
    "years",
}

VECTOR_NAME_TOKENS = {
    "embedding",
    "embeddings",
    "feature",
    "features",
    "image",
    "img",
    "pixel",
    "pixels",
    "vector",
    "vectors",
}

FREE_TEXT_NAME_TOKENS = {
    "comment",
    "complaint",
    "description",
    "details",
    "message",
    "narrative",
    "note",
    "notes",
    "review",
    "summary",
    "text",
}

BOOLEAN_TEXT_VALUES = {
    "0",
    "1",
    "false",
    "f",
    "no",
    "n",
    "true",
    "t",
    "yes",
    "y",
}

NUMERIC_TOKEN_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Keep confidence/math helper values inside a stable range."""
    return max(low, min(high, float(value)))


CONFIDENCE_INTERVAL_Z = 1.96


def wilson_interval(successes: int, total: int, z: float = CONFIDENCE_INTERVAL_Z) -> tuple[float, float]:
    """Return a Wilson score interval for a measured proportion."""
    if total <= 0:
        return 0.0, 1.0

    successes = max(0, min(int(successes), int(total)))
    total = int(total)
    observed = successes / total
    z_squared = z * z
    denominator = 1.0 + (z_squared / total)
    center = (observed + (z_squared / (2.0 * total))) / denominator
    margin = (
        z
        * math.sqrt((observed * (1.0 - observed) / total) + (z_squared / (4.0 * total * total)))
        / denominator
    )
    return clamp(center - margin), clamp(center + margin)


def interval_summary(successes: int, total: int) -> dict[str, float]:
    """Summarize a measured proportion and its uncertainty."""
    observed = float(successes / total) if total > 0 else 0.0
    lower, upper = wilson_interval(successes, total)
    return {
        "observed": clamp(observed),
        "lower": lower,
        "upper": upper,
        "margin": max(observed - lower, upper - observed),
    }


def interval_summary_from_ratio(ratio: float, total: int) -> dict[str, float]:
    """Build a Wilson interval when a helper already returned only a ratio."""
    successes = int(round(clamp(ratio) * max(0, int(total))))
    return interval_summary(successes, total)


def evidence_interval(successes: int, total: int, enabled: bool = True) -> dict[str, float]:
    """Return a measured interval, or the raw observation for an ablation."""
    if enabled:
        return interval_summary(successes, total)
    observed = float(successes / total) if total > 0 else 0.0
    return {"observed": observed, "lower": observed, "upper": observed, "margin": 0.0}


def hll_relative_standard_error(precision: int = DEFAULT_HLL_PRECISION) -> float:
    """Approximate HyperLogLog relative standard error for the configured precision."""
    return 1.04 / math.sqrt(2**precision)


def cardinality_interval_summary(
    unique_count: int,
    total: int,
    is_estimated: bool,
    *,
    sample_singleton_rows: int | None = None,
    sample_total: int | None = None,
    enabled: bool = True,
) -> dict[str, float]:
    """Estimate key-like uniqueness without treating distinct values as trials.

    For exact samples, the lower bound comes from the proportion of rows whose
    value occurs exactly once. That is a more defensible key signal than using
    ``distinct_count`` as a binomial success count. HLL error is added when the
    full distinct count is estimated.
    """
    observed = clamp(float(unique_count / total) if total > 0 else 0.0)
    if not enabled:
        return {"observed": observed, "lower": observed, "upper": observed, "margin": 0.0}

    if sample_singleton_rows is not None and sample_total:
        singleton_summary = interval_summary(sample_singleton_rows, sample_total)
        lower = min(observed, singleton_summary["lower"])
        upper = max(observed, singleton_summary["upper"])
        summary = {
            "observed": observed,
            "lower": lower,
            "upper": upper,
            "margin": max(observed - lower, upper - observed),
        }
    else:
        finite_sample_margin = CONFIDENCE_INTERVAL_Z * math.sqrt(
            max(observed * (1.0 - observed), 0.25 / max(1, total)) / max(1, total)
        )
        summary = {
            "observed": observed,
            "lower": clamp(observed - finite_sample_margin),
            "upper": clamp(observed + finite_sample_margin),
            "margin": finite_sample_margin,
        }
    if is_estimated:
        hll_margin = summary["observed"] * hll_relative_standard_error()
        summary["lower"] = clamp(summary["observed"] - max(summary["margin"], hll_margin))
        summary["upper"] = clamp(summary["observed"] + max(summary["margin"], hll_margin))
        summary["margin"] = max(summary["observed"] - summary["lower"], summary["upper"] - summary["observed"])
    return summary


def reliability_from_margin(margin: float, unacceptable_margin: float = 0.30) -> float:
    """Convert confidence-interval width into a 0-1 reliability score."""
    return clamp(1.0 - (float(margin) / unacceptable_margin))


def sample_reliability_score(sample_size: int) -> float:
    """Estimate sample reliability from worst-case 95% proportion uncertainty."""
    if sample_size <= 0:
        return 0.0
    worst_case = interval_summary(sample_size // 2, sample_size)
    return reliability_from_margin(worst_case["margin"])


def confidence_bucket(score: float) -> str:
    """Convert a numeric confidence score into a simple user-facing bucket."""
    if score >= 0.80:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def profile_decision_thresholds() -> dict[str, float]:
    """Semantic thresholds for column roles; confidence intervals handle uncertainty."""
    return {
        "numeric_parse_threshold": 0.85,
        "measurement_parse_threshold": 0.75,
        "date_parse_threshold": 0.70,
        "identifier_ratio_threshold": 0.90,
        "datetime_identifier_ratio_threshold": 0.75,
        "id_reference_ratio_threshold": 0.10,
        "id_reference_min_unique": 1000.0,
    }


def append_warning(existing: str, addition: str) -> str:
    """Append a warning sentence without losing older explanations."""
    if not addition:
        return existing
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing} {addition}"


def parse_args() -> argparse.Namespace:
    # argparse lets this script accept command-line options such as:
    #   --multi-dataset
    #   --profile-rows 3000
    #   --detector-rows 500
    parser = argparse.ArgumentParser(description="Profile dataset shape and detector baseline behavior.")

    # One specific CSV file to profile when we are not in multi-dataset mode.
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)

    # A simple on/off flag.  If present, profile every CSV in --dataset-dir.
    parser.add_argument("--multi-dataset", action="store_true", help="Profile all CSV files in --dataset-dir.")

    # Folder containing CSV files for multi-dataset mode.
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)

    # Folder where the script writes output files.
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)

    # Number of rows used to understand the dataset shape.
    # Example: numeric/categorical/free-text counts and missing-value rate.
    parser.add_argument(
        "--profile-rows",
        type=int,
        default=DEFAULT_PROFILE_ROWS,
        help="Rows used for column role and missingness profiling.",
    )

    # Number of rows used to run actual Buckaroo detectors.
    # This gives the baseline error rate.
    parser.add_argument(
        "--detector-rows",
        type=int,
        default=DEFAULT_DETECTOR_ROWS,
        help="Rows used for baseline detector error-rate profiling.",
    )

    parser.add_argument(
        "--cardinality-chunk-rows",
        type=int,
        default=DEFAULT_CARDINALITY_CHUNK_ROWS,
        help="Rows per chunk for full-file approximate distinct counting.",
    )

    parser.add_argument(
        "--ucc-max-arity",
        type=int,
        default=DEFAULT_UCC_MAX_ARITY,
        help="Maximum key-candidate width to test. Buckaroo defaults to singles, pairs, and bounded triples.",
    )

    parser.add_argument(
        "--ucc-max-candidate-columns",
        type=int,
        default=DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
        help="Maximum likely ID/category/date/code columns considered for UCC pairs and triples.",
    )

    parser.add_argument(
        "--ucc-near-unique-threshold",
        type=float,
        default=DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD,
        help="Uniqueness ratio required to report near-unique key candidates and trigger triple checks.",
    )

    # Parse and return the user's command-line choices.
    return parser.parse_args()


def ensure_id_column(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with a stable Buckaroo-style ID column in first position."""
    # Work on a copy so this helper does not accidentally mutate the caller's
    # original dataframe.
    result = df.copy()

    # Buckaroo detectors expect an ID column.  If the CSV already has a good
    # numeric, unique ID column, keep it.
    if "ID" in result.columns:
        # Convert ID values to numbers.  Bad values become NaN instead of
        # crashing, because errors="coerce" is forgiving.
        id_values = pd.to_numeric(result["ID"], errors="coerce")

        # The ID column is usable only if every ID is present and no two rows
        # share the same ID.
        if id_values.notna().all() and id_values.is_unique:
            result["ID"] = id_values.astype(int)

            # Move ID to the first column because the detector code expects
            # Buckaroo-style dataframes to start with ID.
            columns = ["ID"] + [column for column in result.columns if column != "ID"]
            return result[columns]

    # If there is no good ID column, create one: 0, 1, 2, 3, ...
    result.insert(0, "ID", range(len(result)))
    return result


def detector_maps_to_frame(error_maps: list[dict[str, dict[int, Any]]]) -> pd.DataFrame:
    # Detectors return nested dictionaries, which are useful for the app but
    # awkward for experiments.  This function flattens them into a normal table:
    #
    #   row_id | column_id | error_type
    #
    # That makes it easy to count how many rows have errors.
    rows = []

    # error_maps is a list because we run several detectors.
    # Example: anomaly output, missing-value output, type-mismatch output, etc.
    for error_map in error_maps:
        # Each error_map is grouped by column name.
        for column_id, row_errors in error_map.items():
            # Each row_errors dict says which row IDs had errors in that column.
            for row_id, error_record in row_errors.items():
                # Newer detectors may return detailed dictionaries with fields
                # like confidence, severity, and reason.
                if isinstance(error_record, dict):
                    # Prefer the old UI-friendly name if present, otherwise use
                    # the newer detailed error_type.
                    error_type = error_record.get("legacy_error_type") or error_record.get("error_type")
                else:
                    # Older/simple detectors may return just a string like
                    # "missing" or "anomaly".
                    error_type = error_record

                # Skip empty/null error values.
                if pd.notna(error_type):
                    rows.append({"row_id": int(row_id), "column_id": column_id, "error_type": error_type})

    # Return a DataFrame even if rows is empty, with stable column names.
    return pd.DataFrame(rows, columns=["row_id", "column_id", "error_type"])


def run_detectors_direct(df: pd.DataFrame) -> pd.DataFrame:
    """Run the current detector modules without importing the Flask app."""
    # Make sure the detectors receive data in Buckaroo's expected shape.
    df_with_id = ensure_id_column(df)

    # Let Buckaroo choose adaptive detector settings for this dataset.
    # Example: tiny datasets can suppress rare-value detection because "rare"
    # is unreliable when there are very few rows.
    config = infer_detector_config(df_with_id)

    # Convert every non-ID column to numeric once and reuse it.
    # This avoids repeatedly doing pd.to_numeric inside multiple detectors.
    # Non-numeric values become NaN.
    numeric_cache = {
        column: pd.to_numeric(df_with_id[column], errors="coerce")
        for column in df_with_id.columns
        if column != "ID"
    }

    # Run the four Buckaroo detector families on the sampled data.
    error_maps = [
        # Finds numeric outliers, such as extreme salaries or unusual hours.
        anomaly(df_with_id, numeric_cache=numeric_cache, include_details=True, config=config),

        # Finds suspicious rare categorical values.  This detector is named
        # incomplete in the code because of older Buckaroo naming.
        incomplete(df_with_id, numeric_cache=numeric_cache, include_details=True, config=config),

        # Finds missing values such as blank, ?, N/A, null, or unknown.
        missing_value(df_with_id, include_details=True),

        # Finds values that do not match the dominant type of a column.
        # Example: "banana" inside a mostly numeric age column.
        datatype_mismatch(df_with_id, include_details=True, config=config),
    ]

    # Convert all detector outputs into one simple error table.
    return detector_maps_to_frame(error_maps)


def scan_csv_cardinality(
    csv_path: Path,
    chunk_rows: int = DEFAULT_CARDINALITY_CHUNK_ROWS,
) -> tuple[int, dict[str, DistinctCountProfile]]:
    """Estimate full-file distinct counts with bounded memory.

    This is the Buckaroo-friendly version of the Metanome HyperLogLog idea:
    scan the CSV in chunks, keep exact sets only while they are small, and
    switch to HyperLogLog registers for high-cardinality columns.
    """

    total_rows = 0
    accumulators: dict[str, DistinctCountAccumulator] = {}

    for chunk in pd.read_csv(csv_path, chunksize=max(1, chunk_rows), low_memory=False):
        total_rows += int(len(chunk))

        if not accumulators:
            accumulators = {
                column: DistinctCountAccumulator(
                    exact_limit=DEFAULT_DISTINCT_EXACT_LIMIT,
                    precision=DEFAULT_HLL_PRECISION,
                    normalize_text=True,
                )
                for column in chunk.columns
            }

        for column in chunk.columns:
            valid = chunk[column][~chunk[column].map(is_missing_value)]
            accumulators[column].add_many(valid)

    return total_rows, {column: accumulator.profile() for column, accumulator in accumulators.items()}


def name_tokens(column: str) -> set[str]:
    """Split a column name into lowercase words for simple name-hint checks.

    Splits on non-alphanumeric separators (space/underscore/hyphen) AND on
    camelCase/PascalCase boundaries, so "DevType" yields {"dev", "type"} and
    "RaceEthnicity" yields {"race", "ethnicity"} instead of one fused token
    that can never match a hint keyword. Boundaries must be found before
    lowercasing -- case is the only signal that separates the words.
    """
    text = str(column).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def has_name_hint(tokens: set[str], hint_tokens: set[str]) -> bool:
    """Return True if the column-name tokens contain any known hint token."""
    return bool(tokens.intersection(hint_tokens))


def normalized_column_name(column: str) -> str:
    """Normalize a column name for suffix/exact-match semantic checks."""
    return str(column).strip().lower().replace(" ", "_").replace("-", "_")


def geography_kind(column: str) -> str | None:
    """Classify geography/location hints from a column name.

    These hints intentionally protect common geography fields from being
    promoted to primary keys solely because they are unique.
    """
    normalized = normalized_column_name(column)
    tokens = name_tokens(column)

    if tokens.intersection(LATITUDE_NAME_TOKENS):
        return "latitude"
    if tokens.intersection(LONGITUDE_NAME_TOKENS):
        return "longitude"
    if tokens.intersection(POSTAL_NAME_TOKENS):
        return "postal_code"
    if normalized in {"iata", "icao"} or (
        "airport" in tokens and ("code" in tokens or "id" in tokens or normalized.endswith("_code"))
    ):
        return "airport_code"
    if "country" in tokens and ("code" in tokens or normalized.endswith("_code")):
        return "country_code"
    if tokens.intersection(LOCATION_NAME_TOKENS):
        return "location_name"
    return None


def coordinate_values_in_range(kind: str | None, numeric: pd.Series, numeric_ratio: float) -> bool:
    """Return True when values look like valid latitude/longitude numbers."""
    if kind not in {"latitude", "longitude"} or numeric_ratio < 0.75:
        return False

    values = numeric.dropna().astype(float)
    if values.empty:
        return False

    if kind == "latitude":
        return bool(values.between(-90.0, 90.0).mean() >= 0.95)
    return bool(values.between(-180.0, 180.0).mean() >= 0.95)


def is_geography_signal(column: str, profile_role: str = "") -> bool:
    """Return True when a column should be treated as geography, not identity."""
    return profile_role in GEOGRAPHY_PROFILE_ROLES or geography_kind(column) is not None


def date_like_ratio(values_as_text: pd.Series) -> float:
    """Estimate what fraction of sampled values look parseable as dates.

    Plain numbers such as age=42 can be misread by pandas as dates, so this
    helper only tries values with obvious date/time shapes first.
    """
    sample = (
        values_as_text.sample(n=200, replace=False, random_state=20260714)
        if len(values_as_text) > 200
        else values_as_text
    )
    if sample.empty:
        return 0.0

    date_shaped = sample.map(lambda value: bool(re.search(r"[-/:]", str(value))))
    if not bool(date_shaped.any()):
        return 0.0

    parsed = pd.to_datetime(sample.where(date_shaped), errors="coerce", format="mixed", utc=True)
    return float(parsed.notna().mean())


def boolean_like_ratio(values_as_text: pd.Series) -> float:
    """Estimate what fraction of values are common boolean encodings."""
    if values_as_text.empty:
        return 0.0
    normalized = values_as_text.str.strip().str.lower()
    return float(normalized.isin(BOOLEAN_TEXT_VALUES).mean())


def integer_profile(numeric: pd.Series) -> dict[str, Any]:
    """Measure whether numeric values look like small integer codes."""
    numeric_values = numeric.dropna().astype(float)
    if numeric_values.empty:
        return {
            "all_integer": False,
            "has_decimal_values": False,
            "numeric_min": None,
            "numeric_max": None,
            "integer_range_coverage": 0.0,
        }

    rounded = numeric_values.round()
    integer_mask = (numeric_values - rounded).abs() < 1e-9
    all_integer = bool(integer_mask.all())
    has_decimal_values = bool((~integer_mask).any())
    numeric_min = float(numeric_values.min())
    numeric_max = float(numeric_values.max())

    integer_range_coverage = 0.0
    if all_integer:
        unique_count = int(numeric_values.nunique(dropna=True))
        integer_range_width = int(numeric_max - numeric_min + 1)
        if integer_range_width > 0:
            integer_range_coverage = float(unique_count / integer_range_width)

    return {
        "all_integer": all_integer,
        "has_decimal_values": has_decimal_values,
        "numeric_min": numeric_min,
        "numeric_max": numeric_max,
        "integer_range_coverage": integer_range_coverage,
    }


def numeric_token_profile(values_as_text: pd.Series) -> dict[str, float]:
    """Measure whether long text values are actually numeric vectors.

    A pixel column from image datasets may contain thousands of numbers in one
    string.  It is text storage, but it is not natural language text, so SBERT
    should not treat it like a complaint narrative or description.
    """
    sample = values_as_text.head(100)
    token_counts: list[int] = []
    total_tokens = 0
    numeric_tokens = 0
    bounded_0_255_tokens = 0

    for value in sample:
        tokens = str(value).strip().split()
        if not tokens:
            continue

        token_counts.append(len(tokens))
        for token in tokens:
            total_tokens += 1
            if NUMERIC_TOKEN_PATTERN.match(token):
                numeric_tokens += 1
                number = float(token)
                if 0.0 <= number <= 255.0:
                    bounded_0_255_tokens += 1

    if not total_tokens:
        return {
            "numeric_token_fraction": 0.0,
            "bounded_0_255_token_fraction": 0.0,
            "fixed_token_count_ratio": 0.0,
        }

    token_count_mode = Counter(token_counts).most_common(1)[0][1] if token_counts else 0
    fixed_token_count_ratio = float(token_count_mode / max(1, len(token_counts)))

    return {
        "numeric_token_fraction": float(numeric_tokens / total_tokens),
        "bounded_0_255_token_fraction": float(bounded_0_255_tokens / total_tokens),
        "fixed_token_count_ratio": fixed_token_count_ratio,
    }


def choose_profile_result(
    role: str,
    profile_role: str,
    confidence: str,
    reason: str,
    warning: str = "",
) -> dict[str, str]:
    """Package the role decision in one consistent shape."""
    return {
        "role": role,
        "profile_role": profile_role,
        "confidence": confidence,
        "reason": reason,
        "warning": warning,
    }


def score_profile_confidence(
    profile_role: str,
    bool_ratio: float,
    decision_cardinality_ratio: float,
    avg_text_length: float,
    avg_word_count: float,
    thresholds: dict[str, float],
    evidence_intervals: dict[str, dict[str, float]],
    sample_distinct: DistinctCountProfile,
    full_profile: DistinctCountProfile,
    id_name_hint: bool,
    categorical_name_hint: bool,
    measurement_name_hint: bool,
    free_text_name_hint: bool,
    vector_name_hint: bool,
    geography_name_hint: bool,
) -> float:
    """Score how trustworthy the chosen profile role is from 0.0 to 1.0."""
    relevant_interval = evidence_intervals["sample"]

    if profile_role in {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"}:
        relevant_interval = evidence_intervals["date_parse"]
        evidence = clamp(relevant_interval["lower"] / max(0.01, thresholds["date_parse_threshold"]))
    elif profile_role in {"identifier", "quasi_identifier"}:
        relevant_interval = evidence_intervals["cardinality"]
        threshold = (
            thresholds["id_reference_ratio_threshold"]
            if profile_role == "identifier" and id_name_hint
            else thresholds["identifier_ratio_threshold"]
        )
        evidence = clamp(decision_cardinality_ratio / max(0.01, threshold))
        evidence = min(evidence, clamp(relevant_interval["lower"] / max(0.01, threshold)))
        if id_name_hint:
            evidence = max(evidence, 0.75)
    elif profile_role == "numeric_measure":
        relevant_interval = evidence_intervals["numeric_parse"]
        threshold = (
            thresholds["measurement_parse_threshold"]
            if measurement_name_hint
            else thresholds["numeric_parse_threshold"]
        )
        evidence = clamp(relevant_interval["lower"] / max(0.01, threshold))
    elif profile_role in GEOGRAPHY_PROFILE_ROLES:
        relevant_interval = evidence_intervals["cardinality"]
        evidence = 0.90 if geography_name_hint else 0.70
        if profile_role == "geographic_coordinate":
            evidence = max(evidence, clamp(evidence_intervals["numeric_parse"]["lower"] / 0.75))
    elif profile_role == "numeric_code_category":
        relevant_interval = evidence_intervals["numeric_parse"]
        evidence = max(clamp(relevant_interval["lower"] / max(0.01, thresholds["numeric_parse_threshold"])), 0.70)
        if categorical_name_hint:
            evidence = max(evidence, 0.90)
    elif profile_role == "binary_category":
        relevant_interval = evidence_intervals["boolean_parse"]
        evidence = max(clamp(bool_ratio / 0.95), 1.0 if decision_cardinality_ratio <= 0.02 else 0.80)
    elif profile_role == "vector_blob":
        relevant_interval = evidence_intervals["sample"]
        evidence = 0.95 if vector_name_hint else 0.85
    elif profile_role == "free_text":
        relevant_interval = evidence_intervals["cardinality"]
        evidence = 0.90 if free_text_name_hint else clamp((avg_word_count / 10.0) + (avg_text_length / 120.0))
    elif profile_role == "categorical":
        relevant_interval = evidence_intervals["cardinality"]
        evidence = max(0.55, clamp(1.0 - decision_cardinality_ratio))
        if categorical_name_hint:
            evidence = max(evidence, 0.75)
    else:
        evidence = 0.50

    # Column-aware reliability, not a dataset-wide floor. relevant_interval is
    # already the column's own evidence interval (cardinality for categorical
    # columns, numeric-parse for measures, etc.), and its margin already widens
    # for small samples and for HLL-estimated cardinality (see
    # cardinality_interval_summary) -- so it already accounts for sample-size
    # uncertainty in a column-appropriate way. Previously this was additionally
    # min()'d against evidence_intervals["sample"]["reliability"], a *dataset-wide*
    # worst-case bound built from an assumed 50/50 split (evidence_interval(n//2,
    # n, ...)) -- a fixed ceiling derived from sample size alone, identical for
    # every column regardless of how well-separated that column's own values
    # are. Found live: at n=400 this ceiling sat at 0.837, capping a perfectly
    # clean, well-separated column (11 distinct bucketed values, tight cardinality
    # margin) at the same reliability as a genuinely ambiguous one -- the shared
    # ceiling, not the column's own evidence, was deciding the outcome. For roles
    # where relevant_interval already *is* evidence_intervals["sample"] (vector_
    # blob, high-uniqueness/identifier datetime roles), this is a no-op: the two
    # values are identical there, so nothing changes for those roles.
    reliability = reliability_from_margin(relevant_interval["margin"])

    name_hint_score = 0.0
    if (
        (profile_role in {"identifier", "quasi_identifier"} and id_name_hint)
        or (profile_role in {"categorical", "numeric_code_category", "binary_category"} and categorical_name_hint)
        or (profile_role == "numeric_measure" and measurement_name_hint)
        or (profile_role == "free_text" and free_text_name_hint)
        or (profile_role == "vector_blob" and vector_name_hint)
        or (profile_role in GEOGRAPHY_PROFILE_ROLES and geography_name_hint)
    ):
        name_hint_score = 1.0

    score = (0.50 * evidence) + (0.40 * reliability) + (0.10 * name_hint_score)

    cardinality_interval = evidence_intervals["cardinality"]
    if profile_role in {"identifier", "quasi_identifier"}:
        threshold = (
            thresholds["id_reference_ratio_threshold"]
            if profile_role == "identifier" and id_name_hint
            else thresholds["identifier_ratio_threshold"]
        )
        if cardinality_interval["observed"] >= threshold and cardinality_interval["lower"] < threshold:
            score -= 0.10
    elif profile_role in {"datetime_high_uniqueness", "datetime_identifier"}:
        threshold = thresholds["datetime_identifier_ratio_threshold"]
        if cardinality_interval["observed"] >= threshold and cardinality_interval["lower"] < threshold:
            score -= 0.10
    if sample_distinct.is_estimated or full_profile.is_estimated:
        score -= 0.03

    return clamp(score)


def score_candidate_confidence(
    evidence_strength: float,
    relevant_interval: dict[str, float],
    evidence_intervals: dict[str, dict[str, float]],
    *,
    name_hint: bool = False,
) -> float:
    """Put every candidate role on one UI-facing confidence scale.

    The raw detector evidence answers "does this signal exist?"  The normalized
    confidence answers "how much should Buckaroo trust this role after sample
    reliability and interval width are considered?"  Keeping those separate
    prevents broad roles and subtypes from displaying incompatible percentages.
    """
    evidence_strength = clamp(evidence_strength)
    if evidence_strength <= 0.0 and not name_hint:
        return 0.0

    # Column-aware reliability, not a dataset-wide floor -- see the identical
    # fix and full rationale on score_profile_confidence's reliability line
    # above. Fixed in both places so a candidate role's displayed confidence
    # and the chosen role's confidence stay on the same, consistent basis.
    reliability = reliability_from_margin(relevant_interval["margin"])
    name_hint_score = 1.0 if name_hint else 0.0
    return clamp((0.50 * evidence_strength) + (0.40 * reliability) + (0.10 * name_hint_score))


def align_chosen_candidate_confidence(
    candidate_roles: list[dict[str, Any]],
    chosen_candidate_role: str,
    chosen_confidence_score: float,
) -> list[dict[str, Any]]:
    """Make the chosen candidate and displayed role share one confidence value."""
    aligned: list[dict[str, Any]] = []
    for candidate in candidate_roles:
        updated = dict(candidate)
        updated["chosen"] = updated.get("role") == chosen_candidate_role
        if updated["chosen"]:
            updated["confidence"] = round(clamp(chosen_confidence_score), 3)
            updated["confidence_basis"] = "chosen_profile_confidence"
        aligned.append(updated)

    aligned.sort(key=lambda candidate: (-float(candidate["confidence"]), str(candidate["role"])))
    return aligned


def build_candidate_roles(
    *,
    chosen_role: str,
    chosen_profile_role: str,
    bool_ratio: float,
    numeric_ratio: float,
    date_ratio: float,
    decision_cardinality_ratio: float,
    avg_text_length: float,
    avg_word_count: float,
    thresholds: dict[str, float],
    evidence_intervals: dict[str, dict[str, float]],
    id_name_hint: bool,
    categorical_name_hint: bool,
    measurement_name_hint: bool,
    free_text_name_hint: bool,
    geography_name_hint: bool,
    geo_kind: str | None,
    coordinate_like: bool,
    semantic_text_candidate: bool,
    small_integer_domain: bool,
    numeric_code_like: bool,
) -> list[dict[str, Any]]:
    """Return multiple plausible semantic roles with confidence scores.

    This is intentionally explainable rather than ML-like: each candidate is
    scored from visible profiler evidence, so the UI can show why Buckaroo is
    confident or uncertain.
    """
    numeric_threshold = (
        thresholds["measurement_parse_threshold"]
        if measurement_name_hint
        else thresholds["numeric_parse_threshold"]
    )
    numeric_score = clamp(evidence_intervals["numeric_parse"]["lower"] / max(0.01, numeric_threshold))
    if measurement_name_hint:
        numeric_score = min(1.0, numeric_score + 0.10)
    if numeric_code_like or small_integer_domain:
        numeric_score *= 0.55
    if geography_name_hint:
        numeric_score = min(numeric_score, 0.55 if geo_kind in {"latitude", "longitude"} else 0.30)

    categorical_score = max(
        0.10,
        clamp(1.0 - decision_cardinality_ratio),
        clamp(bool_ratio / 0.95),
        0.85 if categorical_name_hint else 0.0,
        0.90 if small_integer_domain or numeric_code_like else 0.0,
    )
    if chosen_profile_role == "numeric_measure" and not categorical_name_hint:
        categorical_score = min(categorical_score, 0.35)

    identifier_threshold = (
        thresholds["id_reference_ratio_threshold"]
        if id_name_hint
        else thresholds["identifier_ratio_threshold"]
    )
    identifier_score = clamp(
        evidence_intervals["cardinality"]["lower"] / max(0.01, identifier_threshold)
    )
    if id_name_hint:
        identifier_score = min(1.0, max(identifier_score, 0.70))
    if chosen_profile_role in {
        "datetime_high_uniqueness",
        "geographic_coordinate",
        "high_uniqueness_location_field",
        "location_name",
        "postal_code",
        "airport_code",
        "country_code",
    }:
        identifier_score = min(identifier_score, 0.20)
    if chosen_profile_role == "numeric_measure" and not id_name_hint:
        identifier_score = min(identifier_score, 0.20)

    datetime_score = clamp(evidence_intervals["date_parse"]["lower"] / max(0.01, thresholds["date_parse_threshold"]))

    geography_score = 0.0
    if geography_name_hint:
        geography_score = 0.90
        if geo_kind in {"latitude", "longitude"} and coordinate_like:
            geography_score = 0.98
        elif geo_kind in {"postal_code", "airport_code", "country_code"}:
            geography_score = 0.92

    free_text_score = 0.0
    if semantic_text_candidate:
        free_text_score = 0.82 if free_text_name_hint else clamp((avg_word_count / 10.0) + (avg_text_length / 120.0))

    candidates = [
        {
            "role": "numeric_measure",
            "evidence_strength": round(numeric_score, 3),
            "confidence": round(
                score_candidate_confidence(
                    numeric_score,
                    evidence_intervals["numeric_parse"],
                    evidence_intervals,
                    name_hint=measurement_name_hint,
                ),
                3,
            ),
            "confidence_basis": "normalized_candidate_confidence_v1",
            "reason": "numeric parse evidence and measurement-name hints",
        },
        {
            "role": "categorical",
            "evidence_strength": round(categorical_score, 3),
            "confidence": round(
                score_candidate_confidence(
                    categorical_score,
                    evidence_intervals["cardinality"],
                    evidence_intervals,
                    name_hint=categorical_name_hint or small_integer_domain or numeric_code_like,
                ),
                3,
            ),
            "confidence_basis": "normalized_candidate_confidence_v1",
            "reason": "repeated values, boolean/category hints, or small code domain",
        },
        {
            "role": "primary_key",
            "evidence_strength": round(identifier_score, 3),
            "confidence": round(
                score_candidate_confidence(
                    identifier_score,
                    evidence_intervals["cardinality"],
                    evidence_intervals,
                    name_hint=id_name_hint,
                ),
                3,
            ),
            "confidence_basis": "normalized_candidate_confidence_v1",
            "reason": "uniqueness confidence interval and ID-like name hints",
        },
        {
            "role": "datetime",
            "evidence_strength": round(datetime_score, 3),
            "confidence": round(
                score_candidate_confidence(
                    datetime_score,
                    evidence_intervals["date_parse"],
                    evidence_intervals,
                    name_hint=False,
                ),
                3,
            ),
            "confidence_basis": "normalized_candidate_confidence_v1",
            "reason": "date/time parse evidence",
        },
        {
            "role": "geography_location",
            "evidence_strength": round(geography_score, 3),
            "confidence": round(
                score_candidate_confidence(
                    geography_score,
                    evidence_intervals["numeric_parse"] if coordinate_like else evidence_intervals["cardinality"],
                    evidence_intervals,
                    name_hint=geography_name_hint,
                ),
                3,
            ),
            "confidence_basis": "normalized_candidate_confidence_v1",
            "reason": "geography/location name hints and coordinate/code safeguards",
        },
        {
            "role": "free_text",
            "evidence_strength": round(free_text_score, 3),
            "confidence": round(
                score_candidate_confidence(
                    free_text_score,
                    evidence_intervals["cardinality"],
                    evidence_intervals,
                    name_hint=free_text_name_hint,
                ),
                3,
            ),
            "confidence_basis": "normalized_candidate_confidence_v1",
            "reason": "wordy natural-language text evidence",
        },
    ]

    for candidate in candidates:
        candidate["chosen"] = candidate["role"] == semantic_candidate_role(chosen_role, chosen_profile_role)

    candidates.sort(key=lambda candidate: (-float(candidate["confidence"]), str(candidate["role"])))
    return candidates


def semantic_candidate_role(chosen_role: str, chosen_profile_role: str) -> str:
    """Map Buckaroo's detailed profile role to the candidate-role vocabulary."""
    if chosen_profile_role in {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"}:
        return "datetime"
    if chosen_profile_role in GEOGRAPHY_PROFILE_ROLES:
        return "geography_location"
    if chosen_profile_role in {"identifier", "quasi_identifier"} or chosen_role == "identifier":
        return "primary_key"
    if chosen_profile_role in {"free_text", "vector_blob"}:
        return "free_text"
    if chosen_profile_role == "numeric_measure" or chosen_role == "numeric":
        return "numeric_measure"
    return "categorical"


def adaptive_sampling_recommendation(
    candidate_roles: list[dict[str, Any]],
    confidence_score: float,
    sample_uncertainty_margin: float,
    total_rows: int,
    chosen_candidate_role: str | None = None,
) -> dict[str, Any]:
    """Use confidence to decide whether Buckaroo should sample more rows."""
    if not candidate_roles:
        return {
            "needs_more_sampling": True,
            "adaptive_sampling_action": "sample_more",
            "adaptive_sampling_reason": "No candidate-role confidence scores were available.",
            "candidate_confidence_gap": 0.0,
            "top_candidate_role": "unknown",
            "top_candidate_confidence": 0.0,
            "second_candidate_role": "unknown",
            "second_candidate_confidence": 0.0,
            "chosen_candidate_role": "unknown",
            "chosen_candidate_confidence": 0.0,
        }

    top = candidate_roles[0]
    second = candidate_roles[1] if len(candidate_roles) > 1 else {"role": "none", "confidence": 0.0}
    top_confidence = float(top["confidence"])
    second_confidence = float(second["confidence"])
    gap = round(top_confidence - second_confidence, 3)
    chosen_candidate = next(
        (candidate for candidate in candidate_roles if candidate.get("role") == chosen_candidate_role),
        top,
    )
    chosen_confidence = float(chosen_candidate["confidence"])

    reasons = []
    if confidence_score < 0.80:
        reasons.append("chosen-role confidence is below 0.80")
    if chosen_candidate_role and str(top.get("role")) != chosen_candidate_role:
        reasons.append("another candidate role has stronger evidence than the chosen role")
    if gap < 0.15:
        reasons.append("top two candidate roles are too close")
    if sample_uncertainty_margin >= 0.10 and total_rows < 50_000:
        reasons.append("95% sample confidence interval is still wide")

    needs_more = bool(reasons)
    return {
        "needs_more_sampling": needs_more,
        "adaptive_sampling_action": "sample_more" if needs_more else "stop",
        "adaptive_sampling_reason": "; ".join(reasons) if reasons else "high confidence, clear candidate gap, and acceptable interval width",
        "candidate_confidence_gap": gap,
        "top_candidate_role": top["role"],
        "top_candidate_confidence": round(top_confidence, 3),
        "second_candidate_role": second["role"],
        "second_candidate_confidence": round(second_confidence, 3),
        "chosen_candidate_role": str(chosen_candidate.get("role", "unknown")),
        "chosen_candidate_confidence": round(chosen_confidence, 3),
    }


def classify_column(
    column: str,
    series: pd.Series,
    full_distinct_profile: DistinctCountProfile | None = None,
    features: ProfilerFeatureFlags = DEFAULT_PROFILER_FEATURES,
) -> dict[str, Any]:
    # Remove values Buckaroo considers missing.  We only classify the column
    # using values that are actually present.
    non_missing = series[~series.map(is_missing_value)]
    non_missing_count = int(len(non_missing))
    thresholds = profile_decision_thresholds()
    sample_reliability = sample_reliability_score(non_missing_count)

    # If a column has no real values, we cannot learn much from it.  Treat it as
    # categorical by default and return zero statistics.
    if non_missing_count == 0:
        return {
            "role": "categorical",
            "profile_role": "empty",
            "confidence": "low",
            "confidence_bucket": "low",
            "confidence_score": 0.0,
            "sample_reliability": 0.0,
            "reason": "No non-missing values were available for profiling.",
            "warning": "Empty columns need manual review before detector tuning.",
            "adaptive_warning": "Empty columns need manual review before detector tuning.",
            "non_missing_count": 0,
            "unique_count": 0,
            "cardinality_ratio": 0.0,
            "distinct_count_method": "exact",
            "unique_count_is_estimated": False,
            "full_estimated_unique_count": 0,
            "full_estimated_cardinality_ratio": 0.0,
            "full_distinct_count_method": "exact",
            "full_unique_count_is_estimated": False,
            "full_non_missing_count": 0,
            "decision_unique_count": 0,
            "decision_cardinality_ratio": 0.0,
            "numeric_ratio": 0.0,
            "date_like_ratio": 0.0,
            "boolean_like_ratio": 0.0,
            "avg_text_length": 0.0,
            "avg_word_count": 0.0,
            "all_integer": False,
            "has_decimal_values": False,
            "small_integer_domain": False,
            "integer_range_coverage": 0.0,
            "numeric_token_fraction": 0.0,
            "bounded_0_255_token_fraction": 0.0,
            "fixed_token_count_ratio": 0.0,
            "id_name_hint": False,
            "categorical_name_hint": False,
            "measurement_name_hint": False,
            "vector_name_hint": False,
            "free_text_name_hint": False,
            "geography_name_hint": False,
            "geography_kind": "",
            "semantic_text_candidate": False,
            "sample_uncertainty_margin": 1.0,
            "numeric_parse_lower_bound": 0.0,
            "numeric_parse_upper_bound": 1.0,
            "numeric_parse_margin": 1.0,
            "date_parse_lower_bound": 0.0,
            "date_parse_upper_bound": 1.0,
            "date_parse_margin": 1.0,
            "cardinality_ratio_lower_bound": 0.0,
            "cardinality_ratio_upper_bound": 1.0,
            "cardinality_ratio_margin": 1.0,
            "confidence_interval_method": (
                "singleton_row_wilson_plus_hll_95"
                if features.use_confidence_intervals
                else "disabled_observed_values_only"
            ),
            "confidence_interval_z": CONFIDENCE_INTERVAL_Z,
            "chosen_role": "categorical",
            "chosen_profile_role": "empty",
            "candidate_roles": [],
            "candidate_roles_json": "[]",
            "top_candidate_role": "unknown",
            "top_candidate_confidence": 0.0,
            "second_candidate_role": "unknown",
            "second_candidate_confidence": 0.0,
            "chosen_candidate_role": "unknown",
            "chosen_candidate_confidence": 0.0,
            "candidate_confidence_gap": 0.0,
            "needs_more_sampling": bool(features.enable_adaptive_sampling),
            "adaptive_sampling_action": "sample_more" if features.enable_adaptive_sampling else "disabled",
            "adaptive_sampling_reason": (
                "No non-missing values were available."
                if features.enable_adaptive_sampling
                else "Adaptive sampling is disabled for this profiler variant."
            ),
            "numeric_parse_threshold": thresholds["numeric_parse_threshold"],
            "measurement_parse_threshold": thresholds["measurement_parse_threshold"],
            "date_parse_threshold": thresholds["date_parse_threshold"],
            "identifier_ratio_threshold": thresholds["identifier_ratio_threshold"],
            "datetime_identifier_ratio_threshold": thresholds["datetime_identifier_ratio_threshold"],
            "id_reference_ratio_threshold": thresholds["id_reference_ratio_threshold"],
            "id_reference_min_unique": int(thresholds["id_reference_min_unique"]),
            "adaptive_thresholds_version": "evidence_interval_v2",
            "profiler_feature_flags": json.dumps(features.__dict__, sort_keys=True),
        }

    # Turn values into stripped text so we can measure text length, word count,
    # and number of unique values consistently.
    as_text = non_missing.astype(str).str.strip()

    # Try to turn values into numbers.  Values that are not numbers become NaN.
    numeric = pd.to_numeric(non_missing, errors="coerce")

    # Fraction of present values that successfully became numbers.
    # Example: 90 numeric-looking values out of 100 means numeric_ratio = 0.9.
    numeric_ratio = float(numeric.notna().mean())

    # Count how many distinct values appear after lowercasing text.
    # Example: USA, usa, and Usa count as the same value.
    sample_distinct = distinct_count_profile(
        as_text,
        exact_limit=DEFAULT_DISTINCT_EXACT_LIMIT,
        precision=DEFAULT_HLL_PRECISION,
        normalize_text=True,
    )
    unique_count = int(sample_distinct.unique_count)

    # Cardinality ratio means: how many values are unique compared to the number
    # of present rows.  A high ratio often means ID-like or free-text data.
    # Example: 900 unique values / 1000 rows = 0.9.
    cardinality_ratio = float(sample_distinct.cardinality_ratio)

    # Use full-file cardinality when available for decisions that care about
    # whether a column is globally key-like.  Keep sample cardinality in the
    # output too, because the sample is what most other evidence came from.
    full_profile = full_distinct_profile or sample_distinct
    decision_unique_count = int(full_profile.unique_count)
    decision_cardinality_ratio = float(full_profile.cardinality_ratio)

    # Average number of characters in each present value.
    avg_text_length = float(as_text.str.len().mean())

    # Average number of words in each present value.
    avg_word_count = float(as_text.str.split().str.len().mean())

    # Name hints help break ties, but they never decide alone.  For example,
    # "ethnicity" hints at a category, but the small integer domain is what
    # lets us call values 0-4 category codes rather than measurements.
    tokens = name_tokens(column)
    id_name_hint = has_name_hint(tokens, ID_NAME_TOKENS)
    categorical_name_hint = has_name_hint(tokens, CATEGORY_CODE_NAME_TOKENS)
    measurement_name_hint = has_name_hint(tokens, MEASUREMENT_NAME_TOKENS)
    vector_name_hint = has_name_hint(tokens, VECTOR_NAME_TOKENS)
    free_text_name_hint = has_name_hint(tokens, FREE_TEXT_NAME_TOKENS)
    detected_geo_kind = geography_kind(column)
    geo_kind = detected_geo_kind if features.use_geography_safeguards else None
    geography_name_hint = geo_kind is not None

    # Extra evidence for the richer research-backed rules.
    date_ratio = date_like_ratio(as_text)
    bool_ratio = boolean_like_ratio(as_text)
    integer_stats = integer_profile(numeric)
    token_stats = numeric_token_profile(as_text)
    date_sample_count = min(200, non_missing_count)
    normalized_counts = as_text.str.lower().value_counts(dropna=False)
    sample_singleton_rows = int(normalized_counts.eq(1).sum())
    sample_interval = evidence_interval(
        non_missing_count // 2,
        non_missing_count,
        features.use_confidence_intervals,
    )
    evidence_intervals = {
        "sample": {
            **sample_interval,
            "reliability": sample_reliability,
        },
        "numeric_parse": evidence_interval(
            int(numeric.notna().sum()),
            non_missing_count,
            features.use_confidence_intervals,
        ),
        "date_parse": evidence_interval(
            int(round(date_ratio * date_sample_count)),
            date_sample_count,
            features.use_confidence_intervals,
        ),
        "boolean_parse": evidence_interval(
            int(round(bool_ratio * non_missing_count)),
            non_missing_count,
            features.use_confidence_intervals,
        ),
        "cardinality": cardinality_interval_summary(
            decision_unique_count,
            max(1, int(full_profile.non_missing_count)),
            bool(full_profile.is_estimated),
            sample_singleton_rows=sample_singleton_rows,
            sample_total=non_missing_count,
            enabled=features.use_confidence_intervals,
        ),
    }

    all_integer = bool(integer_stats["all_integer"])
    integer_range_coverage = float(integer_stats["integer_range_coverage"])

    # A small integer domain is the core signal for numeric-coded categories.
    # Examples: gender 0/1, ethnicity 0-4, labels 1-5, ward/beat codes.
    small_integer_domain = bool(
        numeric_ratio >= thresholds["numeric_parse_threshold"]
        and all_integer
        and decision_unique_count <= 20
        and decision_cardinality_ratio <= 0.05
    )
    dense_integer_code_domain = bool(
        numeric_ratio >= thresholds["numeric_parse_threshold"]
        and all_integer
        and decision_unique_count <= 50
        and integer_range_coverage >= 0.70
        and integer_stats["numeric_min"] is not None
        and float(integer_stats["numeric_min"]) >= 0.0
    )
    numeric_code_like = bool(
        numeric_ratio >= thresholds["numeric_parse_threshold"]
        and all_integer
        and not measurement_name_hint
        and (
            small_integer_domain
            or (categorical_name_hint and decision_cardinality_ratio <= 0.20)
            or (categorical_name_hint and dense_integer_code_domain)
        )
    )

    # Long strings made almost entirely of numbers are not meaningful natural
    # language, even though pandas stores them as text.
    looks_like_vector_blob = bool(
        avg_word_count >= 50
        and token_stats["numeric_token_fraction"] >= 0.95
        and (
            vector_name_hint
            or token_stats["fixed_token_count_ratio"] >= 0.80
            or token_stats["bounded_0_255_token_fraction"] >= 0.95
        )
    )

    # Natural-language text tends to have words and sentences, not only fixed
    # numeric tokens.  This boolean is useful for SBERT gating later.
    semantic_text_candidate = bool(
        not looks_like_vector_blob
        and token_stats["numeric_token_fraction"] < 0.80
        and (
            free_text_name_hint
            or (decision_cardinality_ratio >= 0.20 and (avg_text_length >= 30 or avg_word_count >= 5))
            or avg_word_count >= 10
        )
    )
    id_reference_like = bool(
        id_name_hint
        and (
            cardinality_ratio >= thresholds["id_reference_ratio_threshold"]
            or decision_cardinality_ratio >= thresholds["id_reference_ratio_threshold"]
            or (
                decision_unique_count >= thresholds["id_reference_min_unique"]
                and decision_cardinality_ratio >= min(0.10, thresholds["id_reference_ratio_threshold"])
            )
        )
    )
    coordinate_like = coordinate_values_in_range(geo_kind, numeric, numeric_ratio)

    # Decide the column role.  The order matters:
    #   1. Date-like values get a date explanation before generic categories.
    #   2. Vector blobs are separated from natural-language text.
    #   3. Obvious IDs are protected before numeric parsing.
    #   4. Numeric-coded categories are caught before generic numeric.
    #   5. Remaining high-cardinality short values are quasi-identifiers.
    decision: dict[str, str]
    if date_ratio >= thresholds["date_parse_threshold"]:
        if decision_cardinality_ratio >= thresholds["datetime_identifier_ratio_threshold"]:
            if features.use_timestamp_safeguards:
                decision = choose_profile_result(
                    "categorical",
                    "datetime_high_uniqueness",
                    "medium",
                    "Most sampled values parse as dates and most values are highly unique.",
                    "Timestamp uniqueness alone is not enough primary-key evidence; treat this as a high-uniqueness timestamp unless another key signal exists.",
                )
            else:
                decision = choose_profile_result(
                    "identifier",
                    "identifier",
                    "medium",
                    "High observed uniqueness was accepted without the timestamp safeguard.",
                    "Ablation variant: timestamp safeguards are disabled.",
                )
        else:
            decision = choose_profile_result(
                "categorical",
                "datetime_category",
                "medium",
                "Most sampled values parse as dates, but values repeat enough to group rows.",
            )
    elif looks_like_vector_blob:
        decision = choose_profile_result(
            "free_text",
            "vector_blob",
            "high",
            "Values are long fixed-width numeric token strings, such as pixels or embeddings.",
            "Stored as text, but not semantically rich natural language for SBERT.",
        )
    elif geo_kind in {"latitude", "longitude"} and coordinate_like:
        decision = choose_profile_result(
            "categorical",
            "geographic_coordinate",
            "high",
            "The column name and numeric range look like a latitude/longitude coordinate.",
            "Geographic coordinates can be highly unique, but location uniqueness is not row identity.",
        )
    elif geo_kind == "postal_code":
        decision = choose_profile_result(
            "categorical",
            "postal_code",
            "high",
            "The column name looks like a ZIP/postal code.",
            "Postal codes are location codes; do not promote them to primary keys without a stronger entity-key signal.",
        )
    elif geo_kind == "airport_code":
        decision = choose_profile_result(
            "categorical",
            "airport_code",
            "high",
            "The column name looks like an airport/IATA/ICAO code.",
            "Airport codes identify places or airports, but geography/reference codes should not become row IDs solely from uniqueness.",
        )
    elif geo_kind == "country_code":
        decision = choose_profile_result(
            "categorical",
            "country_code",
            "high",
            "The column name looks like a country code.",
            "Country codes are geography codes, not row identity.",
        )
    elif geo_kind == "location_name":
        if decision_cardinality_ratio >= thresholds["identifier_ratio_threshold"]:
            decision = choose_profile_result(
                "categorical",
                "high_uniqueness_location_field",
                "medium",
                "The column name looks geographic and most observed values are unique.",
                "High-uniqueness location fields can look key-like, but geography/name uniqueness alone is not primary-key evidence.",
            )
        else:
            decision = choose_profile_result(
                "categorical",
                "location_name",
                "high",
                "The column name looks like a city/state/country/zone/location field.",
                "Location fields describe places and should be grouped or validated as geography, not treated as row IDs.",
            )
    elif id_reference_like:
        decision = choose_profile_result(
            "identifier",
            "identifier",
            "high",
            "The column name looks ID-like and values are unique or high-cardinality enough to act as references.",
        )
    elif (decision_unique_count == 2 or bool_ratio >= 0.95) and not (
        numeric_ratio >= thresholds["numeric_parse_threshold"] and measurement_name_hint
    ):
        decision = choose_profile_result(
            "categorical",
            "binary_category",
            "high",
            "The column has exactly two observed values or common boolean encodings.",
        )
    elif numeric_code_like:
        decision = choose_profile_result(
            "categorical",
            "numeric_code_category",
            "high" if categorical_name_hint else "medium",
            "Values parse as numbers, but they form a small integer code domain.",
            "Treat as labels/codes, not continuous measurements.",
        )
    elif (
        numeric_ratio >= thresholds["numeric_parse_threshold"]
        or (measurement_name_hint and numeric_ratio >= thresholds["measurement_parse_threshold"])
    ) and (decision_unique_count > 3 or (measurement_name_hint and decision_unique_count >= 2)):
        decision = choose_profile_result(
            "numeric",
            "numeric_measure",
            "high" if measurement_name_hint and decision_unique_count > 3 else "medium",
            "Most values parse as numbers and measurement evidence outweighs category-code evidence.",
        )
    elif (
        decision_cardinality_ratio >= thresholds["identifier_ratio_threshold"]
        and avg_word_count < 4
        and avg_text_length < 80
    ):
        decision = choose_profile_result(
            "identifier",
            "quasi_identifier",
            "medium",
            "Almost every value is unique and values are short.",
            "High-cardinality short columns are usually not useful semantic categories.",
        )
    elif semantic_text_candidate:
        decision = choose_profile_result(
            "free_text",
            "free_text",
            "high" if free_text_name_hint else "medium",
            "Values are long or wordy enough to look like natural-language text.",
        )
    else:
        decision = choose_profile_result(
            "categorical",
            "categorical",
            "medium",
            "Values repeat enough to behave like labels or groups.",
        )

    profile_confidence_score = score_profile_confidence(
        decision["profile_role"],
        bool_ratio,
        decision_cardinality_ratio,
        avg_text_length,
        avg_word_count,
        thresholds,
        evidence_intervals,
        sample_distinct,
        full_profile,
        id_name_hint,
        categorical_name_hint,
        measurement_name_hint,
        free_text_name_hint,
        vector_name_hint,
        geography_name_hint,
    )
    chosen_candidate_role = semantic_candidate_role(decision["role"], decision["profile_role"])
    if features.include_candidate_roles:
        candidate_roles = build_candidate_roles(
            chosen_role=decision["role"],
            chosen_profile_role=decision["profile_role"],
            bool_ratio=bool_ratio,
            numeric_ratio=numeric_ratio,
            date_ratio=date_ratio,
            decision_cardinality_ratio=decision_cardinality_ratio,
            avg_text_length=avg_text_length,
            avg_word_count=avg_word_count,
            thresholds=thresholds,
            evidence_intervals=evidence_intervals,
            id_name_hint=id_name_hint,
            categorical_name_hint=categorical_name_hint,
            measurement_name_hint=measurement_name_hint,
            free_text_name_hint=free_text_name_hint,
            geography_name_hint=geography_name_hint,
            geo_kind=geo_kind,
            coordinate_like=coordinate_like,
            semantic_text_candidate=semantic_text_candidate,
            small_integer_domain=small_integer_domain,
            numeric_code_like=numeric_code_like,
        )
        candidate_roles = align_chosen_candidate_confidence(
            candidate_roles,
            chosen_candidate_role,
            profile_confidence_score,
        )
        chosen_candidate = next(
            (candidate for candidate in candidate_roles if candidate.get("role") == chosen_candidate_role),
            {"confidence": profile_confidence_score},
        )
        confidence_score = float(chosen_candidate["confidence"])
    else:
        candidate_roles = []
        confidence_score = float(profile_confidence_score)
    final_confidence = confidence_bucket(confidence_score)
    if features.enable_adaptive_sampling:
        sampling_decision = adaptive_sampling_recommendation(
            candidate_roles,
            confidence_score,
            evidence_intervals["sample"]["margin"],
            non_missing_count,
            chosen_candidate_role,
        )
    else:
        sampling_decision = {
            "needs_more_sampling": False,
            "adaptive_sampling_action": "disabled",
            "adaptive_sampling_reason": "Adaptive sampling is disabled for this profiler variant.",
            "candidate_confidence_gap": 0.0,
            "top_candidate_role": chosen_candidate_role,
            "top_candidate_confidence": round(confidence_score, 3),
            "second_candidate_role": "unknown",
            "second_candidate_confidence": 0.0,
            "chosen_candidate_role": chosen_candidate_role,
            "chosen_candidate_confidence": round(confidence_score, 3),
        }

    adaptive_warning = ""
    if evidence_intervals["sample"]["margin"] >= 0.10:
        adaptive_warning = append_warning(
            adaptive_warning,
            "The worst-case 95% evidence margin is wide for this sample, so Buckaroo lowers confidence instead of relying on a row-count cutoff.",
        )
    if decision["profile_role"] in {"identifier", "quasi_identifier"}:
        identifier_threshold = (
            thresholds["id_reference_ratio_threshold"]
            if decision["profile_role"] == "identifier" and id_name_hint
            else thresholds["identifier_ratio_threshold"]
        )
        if (
            evidence_intervals["cardinality"]["observed"] >= identifier_threshold
            and evidence_intervals["cardinality"]["lower"] < identifier_threshold
        ):
            adaptive_warning = append_warning(
                adaptive_warning,
                "Observed uniqueness is high, but the lower confidence bound is below the identifier threshold.",
            )
    if decision["profile_role"] in {"datetime_high_uniqueness", "datetime_identifier"} and (
        evidence_intervals["cardinality"]["observed"] >= thresholds["datetime_identifier_ratio_threshold"]
        and evidence_intervals["cardinality"]["lower"] < thresholds["datetime_identifier_ratio_threshold"]
    ):
        adaptive_warning = append_warning(
            adaptive_warning,
            "Observed timestamp uniqueness is high, but the lower confidence bound is below the high-uniqueness timestamp threshold.",
        )
    if decision["profile_role"] in {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"} and (
        date_ratio < 0.95 or evidence_intervals["date_parse"]["lower"] < thresholds["date_parse_threshold"]
    ):
        adaptive_warning = append_warning(
            adaptive_warning,
            "Some values or confidence-interval bounds failed date parsing evidence, so datetime confidence is reduced.",
        )
    if decision["profile_role"] in GEOGRAPHY_PROFILE_ROLES and decision_cardinality_ratio >= thresholds["identifier_ratio_threshold"]:
        adaptive_warning = append_warning(
            adaptive_warning,
            "Geography/location uniqueness is high, but Buckaroo treats it as location evidence instead of primary-key evidence.",
        )
    if decision["profile_role"] == "numeric_measure" and (
        numeric_ratio < thresholds["numeric_parse_threshold"]
        or evidence_intervals["numeric_parse"]["lower"] < thresholds["numeric_parse_threshold"]
    ):
        adaptive_warning = append_warning(
            adaptive_warning,
            "The numeric decision has uncertainty because some values or lower confidence bounds failed numeric parsing.",
        )
    if sample_distinct.is_estimated or full_profile.is_estimated:
        adaptive_warning = append_warning(
            adaptive_warning,
            "Distinct counts are approximate for this column, so uniqueness confidence includes estimation uncertainty.",
        )
    if final_confidence == "low":
        adaptive_warning = append_warning(
            adaptive_warning,
            "Low confidence means Buckaroo should show the user the evidence instead of treating this as a hard label.",
        )

    decision["confidence"] = final_confidence
    decision["warning"] = append_warning(decision.get("warning", ""), adaptive_warning)

    # Return the role and the evidence used to decide that role.
    return {
        **decision,
        "confidence_bucket": final_confidence,
        "confidence_score": round(confidence_score, 3),
        "chosen_role": decision["role"],
        "chosen_profile_role": decision["profile_role"],
        "candidate_roles": candidate_roles,
        "candidate_roles_json": json.dumps(candidate_roles, sort_keys=True),
        **sampling_decision,
        "sample_reliability": round(sample_reliability, 3),
        "adaptive_warning": adaptive_warning,
        "sample_uncertainty_margin": round(evidence_intervals["sample"]["margin"], 4),
        "non_missing_count": non_missing_count,
        "unique_count": unique_count,
        "cardinality_ratio": round(cardinality_ratio, 4),
        "distinct_count_method": sample_distinct.method,
        "unique_count_is_estimated": bool(sample_distinct.is_estimated),
        "full_estimated_unique_count": int(full_profile.unique_count),
        "full_estimated_cardinality_ratio": round(float(full_profile.cardinality_ratio), 4),
        "full_distinct_count_method": full_profile.method,
        "full_unique_count_is_estimated": bool(full_profile.is_estimated),
        "full_non_missing_count": int(full_profile.non_missing_count),
        "decision_unique_count": decision_unique_count,
        "decision_cardinality_ratio": round(decision_cardinality_ratio, 4),
        "sample_singleton_rows": sample_singleton_rows,
        "sample_singleton_ratio": round(sample_singleton_rows / non_missing_count, 4),
        "numeric_ratio": round(numeric_ratio, 4),
        "date_like_ratio": round(date_ratio, 4),
        "boolean_like_ratio": round(bool_ratio, 4),
        "numeric_parse_lower_bound": round(evidence_intervals["numeric_parse"]["lower"], 4),
        "numeric_parse_upper_bound": round(evidence_intervals["numeric_parse"]["upper"], 4),
        "numeric_parse_margin": round(evidence_intervals["numeric_parse"]["margin"], 4),
        "date_parse_lower_bound": round(evidence_intervals["date_parse"]["lower"], 4),
        "date_parse_upper_bound": round(evidence_intervals["date_parse"]["upper"], 4),
        "date_parse_margin": round(evidence_intervals["date_parse"]["margin"], 4),
        "cardinality_ratio_lower_bound": round(evidence_intervals["cardinality"]["lower"], 4),
        "cardinality_ratio_upper_bound": round(evidence_intervals["cardinality"]["upper"], 4),
        "cardinality_ratio_margin": round(evidence_intervals["cardinality"]["margin"], 4),
        "avg_text_length": round(avg_text_length, 2),
        "avg_word_count": round(avg_word_count, 2),
        "all_integer": all_integer,
        "has_decimal_values": bool(integer_stats["has_decimal_values"]),
        "small_integer_domain": small_integer_domain,
        "integer_range_coverage": round(integer_range_coverage, 4),
        "numeric_token_fraction": round(token_stats["numeric_token_fraction"], 4),
        "bounded_0_255_token_fraction": round(token_stats["bounded_0_255_token_fraction"], 4),
        "fixed_token_count_ratio": round(token_stats["fixed_token_count_ratio"], 4),
        "id_name_hint": id_name_hint,
        "categorical_name_hint": categorical_name_hint,
        "measurement_name_hint": measurement_name_hint,
        "vector_name_hint": vector_name_hint,
        "free_text_name_hint": free_text_name_hint,
        "geography_name_hint": geography_name_hint,
        "geography_kind": (detected_geo_kind or ""),
        "semantic_text_candidate": semantic_text_candidate,
        "confidence_interval_method": (
            "singleton_row_wilson_plus_hll_95"
            if features.use_confidence_intervals
            else "disabled_observed_values_only"
        ),
        "profiler_feature_flags": json.dumps(features.__dict__, sort_keys=True),
        "confidence_interval_z": CONFIDENCE_INTERVAL_Z,
        "numeric_parse_threshold": thresholds["numeric_parse_threshold"],
        "measurement_parse_threshold": thresholds["measurement_parse_threshold"],
        "date_parse_threshold": thresholds["date_parse_threshold"],
        "identifier_ratio_threshold": thresholds["identifier_ratio_threshold"],
        "datetime_identifier_ratio_threshold": thresholds["datetime_identifier_ratio_threshold"],
        "id_reference_ratio_threshold": thresholds["id_reference_ratio_threshold"],
        "id_reference_min_unique": int(thresholds["id_reference_min_unique"]),
        "adaptive_thresholds_version": "evidence_interval_v2",
    }


def profile_columns(
    df: pd.DataFrame,
    full_distinct_profiles: dict[str, DistinctCountProfile] | None = None,
    features: ProfilerFeatureFlags = DEFAULT_PROFILER_FEATURES,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    # records becomes a table with one row per column.
    records = []

    # roles is a convenient lookup of which column names belong to each type.
    roles = {"numeric": [], "categorical": [], "free_text": [], "identifier": []}

    # Check every column in the dataframe.
    for column in df.columns:
        # Skip Buckaroo's row ID column because it is not real user data.
        if column == "ID":
            continue

        # Compute the role and statistics for this column.
        record = classify_column(
            column,
            df[column],
            full_distinct_profile=(full_distinct_profiles or {}).get(column),
            features=features,
        )

        # Store the original column name in the record.
        record["column"] = column

        # Add this column's statistics to the output table.
        records.append(record)

        # Add this column name to its role bucket.
        roles[record["role"]].append(column)

    # Return:
    #   1. A DataFrame/table with column-level statistics.
    #   2. A dictionary of role -> column names.
    return pd.DataFrame(records), roles


def profile_dataset(
    csv_path: Path,
    profile_rows: int,
    detector_rows: int,
    cardinality_chunk_rows: int = DEFAULT_CARDINALITY_CHUNK_ROWS,
    ucc_max_arity: int = DEFAULT_UCC_MAX_ARITY,
    ucc_max_candidate_columns: int = DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
    ucc_near_unique_threshold: float = DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    # Start timing so the report can show how long each dataset took.
    start = time.perf_counter()

    # Scan the full file once in chunks for row count and approximate
    # cardinality.  This avoids storing large distinct-value sets in memory.
    total_rows, full_distinct_profiles = scan_csv_cardinality(csv_path, cardinality_chunk_rows)

    # Read only the rows needed for the profiling and detector samples.  The
    # full-file scan above already captured total row count and cardinality.
    sample_rows = max(1, profile_rows, detector_rows)
    df = pd.read_csv(csv_path, nrows=sample_rows, low_memory=False)

    # Full dataset column count.
    total_columns = int(len(df.columns))

    # Use only the first profile_rows rows for cheap shape profiling.
    # max(1, profile_rows) prevents accidentally taking 0 rows.
    profile_df = df.head(max(1, profile_rows)).copy()

    # Use only the first detector_rows rows for detector profiling.
    # This is separate because detectors are slower than basic counting.
    detector_df = df.head(max(1, detector_rows)).copy()

    # Understand column roles and collect column-level statistics.
    column_profile, roles = profile_columns(profile_df, full_distinct_profiles=full_distinct_profiles)

    # Discover minimal key candidates after the column profiler has identified
    # likely ID/category/date/code columns.  HyperLogLog cardinality is only
    # used for this candidate selection step; reported candidates are validated
    # exactly over tuple hashes by streaming the CSV.
    ucc_candidates = discover_ucc_candidates_in_csv(
        csv_path,
        column_profile,
        chunk_rows=cardinality_chunk_rows,
        max_arity=ucc_max_arity,
        max_candidate_columns=ucc_max_candidate_columns,
        near_unique_threshold=ucc_near_unique_threshold,
    )
    ucc_frame = pd.DataFrame(ucc_candidates)

    # Count missing cells using Buckaroo's missing-value definition.
    # .map(is_missing_value) turns every cell into True/False.
    # First sum counts missing values per column.
    # Second sum counts missing values across all columns.
    missing_cells = int(profile_df.map(is_missing_value).sum().sum())

    # Count the total number of cells inspected:
    #   number of sampled rows * number of columns
    # max(1, ...) prevents division by zero.
    profiled_cells = max(1, int(profile_df.shape[0] * profile_df.shape[1]))

    # Fraction of cells that are missing.
    # Example: 100 missing cells / 10,000 cells = 0.01.
    missing_value_rate = float(missing_cells / profiled_cells)

    # Run Buckaroo detectors on the detector sample.
    errors = run_detectors_direct(detector_df)

    # Number of rows that detectors actually saw.
    detector_sample_rows = int(len(detector_df))

    # Count unique row IDs with at least one detector error.
    # One row can have many errors, but it counts once for baseline error rate.
    rows_with_detector_errors = int(errors["row_id"].nunique()) if not errors.empty else 0

    # Baseline error rate means:
    #   rows with at least one error / rows inspected by detectors
    #
    # This helps semantic clustering know whether a group is truly worse than
    # normal.  If baseline is already 100%, lift is not very informative.
    baseline_error_rate = float(rows_with_detector_errors / max(1, detector_sample_rows))

    # Count how many columns landed in each broad role and richer profile role.
    role_counts = column_profile["role"].value_counts().to_dict() if not column_profile.empty else {}
    profile_role_counts = column_profile["profile_role"].value_counts().to_dict() if not column_profile.empty else {}

    # Semantically rich text means natural-language-ish text that could be a
    # good candidate for SBERT.  Vector blobs are explicitly excluded even
    # though their raw storage is text.
    semantic_text_columns = []
    vector_blob_columns = []
    numeric_code_columns = []
    binary_category_columns = []
    datetime_columns = []
    estimated_cardinality_columns = []
    low_confidence_columns = []
    medium_confidence_columns = []
    high_confidence_columns = []
    adaptive_warning_columns = []
    average_profile_confidence = 0.0
    ucc_candidate_names = []
    unique_single_column_keys = []
    unique_composite_keys = []
    near_unique_ucc_candidates = []
    if not column_profile.empty:
        semantic_text_columns = column_profile.loc[
            column_profile["semantic_text_candidate"],
            "column",
        ].tolist()
        vector_blob_columns = column_profile.loc[
            column_profile["profile_role"] == "vector_blob",
            "column",
        ].tolist()
        numeric_code_columns = column_profile.loc[
            column_profile["profile_role"] == "numeric_code_category",
            "column",
        ].tolist()
        binary_category_columns = column_profile.loc[
            column_profile["profile_role"] == "binary_category",
            "column",
        ].tolist()
        datetime_columns = column_profile.loc[
            column_profile["profile_role"].isin(
                ["datetime_category", "datetime_high_uniqueness", "datetime_identifier"]
            ),
            "column",
        ].tolist()
        estimated_cardinality_columns = column_profile.loc[
            column_profile["full_unique_count_is_estimated"],
            "column",
        ].tolist()
        confidence_counts = column_profile["confidence"].value_counts().to_dict()
        low_confidence_columns = column_profile.loc[
            column_profile["confidence"] == "low",
            "column",
        ].tolist()
        medium_confidence_columns = column_profile.loc[
            column_profile["confidence"] == "medium",
            "column",
        ].tolist()
        high_confidence_columns = column_profile.loc[
            column_profile["confidence"] == "high",
            "column",
        ].tolist()
        adaptive_warning_columns = column_profile.loc[
            column_profile["adaptive_warning"].fillna("").astype(str).str.len() > 0,
            "column",
        ].tolist()
        average_profile_confidence = float(column_profile["confidence_score"].mean())
    else:
        confidence_counts = {}
    if not ucc_frame.empty:
        ucc_candidate_names = ucc_frame["columns"].head(20).tolist()
        unique_single_column_keys = ucc_frame.loc[
            (ucc_frame["is_unique"]) & (ucc_frame["arity"] == 1),
            "columns",
        ].tolist()
        unique_composite_keys = ucc_frame.loc[
            (ucc_frame["is_unique"]) & (ucc_frame["arity"] > 1),
            "columns",
        ].tolist()
        near_unique_ucc_candidates = ucc_frame.loc[
            ~ucc_frame["is_unique"],
            "columns",
        ].tolist()

    # This dictionary becomes one row in dataset_shape_profiles.csv.
    result = {
        "dataset": csv_path.name,
        "source_file": str(csv_path),
        "total_rows": total_rows,
        "total_columns": total_columns,
        "profiled_rows": int(len(profile_df)),
        "detector_sample_rows": detector_sample_rows,
        "numeric_columns": int(role_counts.get("numeric", 0)),
        "categorical_columns": int(role_counts.get("categorical", 0)),
        "free_text_columns": int(role_counts.get("free_text", 0)),
        "identifier_columns": int(role_counts.get("identifier", 0)),
        "numeric_measure_columns": int(profile_role_counts.get("numeric_measure", 0)),
        "numeric_code_category_columns": int(profile_role_counts.get("numeric_code_category", 0)),
        "binary_category_columns": int(profile_role_counts.get("binary_category", 0)),
        "datetime_columns": int(profile_role_counts.get("datetime_category", 0))
        + int(profile_role_counts.get("datetime_high_uniqueness", 0))
        + int(profile_role_counts.get("datetime_identifier", 0)),
        "vector_blob_columns": int(profile_role_counts.get("vector_blob", 0)),
        "semantic_free_text_columns": int(len(semantic_text_columns)),
        "estimated_cardinality_columns": int(len(estimated_cardinality_columns)),
        "average_profile_confidence": round(average_profile_confidence, 3),
        "high_confidence_columns": int(confidence_counts.get("high", 0)),
        "medium_confidence_columns": int(confidence_counts.get("medium", 0)),
        "low_confidence_columns": int(confidence_counts.get("low", 0)),
        "adaptive_warning_columns": int(len(adaptive_warning_columns)),
        "ucc_candidate_count": int(len(ucc_frame)),
        "ucc_unique_single_column_keys": int(len(unique_single_column_keys)),
        "ucc_unique_composite_keys": int(len(unique_composite_keys)),
        "ucc_near_unique_candidates": int(len(near_unique_ucc_candidates)),
        "missing_value_rate": round(missing_value_rate, 4),
        "baseline_error_rate": round(baseline_error_rate, 4),
        "rows_with_detector_errors": rows_with_detector_errors,
        "detector_error_records": int(len(errors)),
        "runtime_seconds": round(time.perf_counter() - start, 3),

        # Store the actual column names too, not only counts.  Limit to 20 so
        # the CSV remains readable for wide datasets.
        "numeric_column_names": "; ".join(roles["numeric"][:20]),
        "categorical_column_names": "; ".join(roles["categorical"][:20]),
        "free_text_column_names": "; ".join(roles["free_text"][:20]),
        "identifier_column_names": "; ".join(roles["identifier"][:20]),
        "numeric_code_category_column_names": "; ".join(numeric_code_columns[:20]),
        "binary_category_column_names": "; ".join(binary_category_columns[:20]),
        "datetime_column_names": "; ".join(datetime_columns[:20]),
        "vector_blob_column_names": "; ".join(vector_blob_columns[:20]),
        "semantic_free_text_column_names": "; ".join(semantic_text_columns[:20]),
        "estimated_cardinality_column_names": "; ".join(estimated_cardinality_columns[:20]),
        "low_confidence_column_names": "; ".join(low_confidence_columns[:20]),
        "medium_confidence_column_names": "; ".join(medium_confidence_columns[:20]),
        "high_confidence_column_names": "; ".join(high_confidence_columns[:20]),
        "adaptive_warning_column_names": "; ".join(adaptive_warning_columns[:20]),
        "ucc_candidate_names": "; ".join(ucc_candidate_names),
        "ucc_unique_single_column_key_names": "; ".join(unique_single_column_keys[:20]),
        "ucc_unique_composite_key_names": "; ".join(unique_composite_keys[:20]),
        "ucc_near_unique_candidate_names": "; ".join(near_unique_ucc_candidates[:20]),
    }

    # Return:
    #   1. Dataset-level summary.
    #   2. Column-level profile table.
    #   3. UCC/key-candidate table.
    return result, column_profile, ucc_frame


def build_report(results: list[dict[str, Any]], args: argparse.Namespace) -> str:
    # Convert the list of dataset summaries into a DataFrame so we can sort and
    # select columns easily.
    frame = pd.DataFrame(results)

    # These are the columns shown in the main report table.
    display_columns = [
        "dataset",
        "total_rows",
        "total_columns",
        "numeric_columns",
        "categorical_columns",
        "free_text_columns",
        "identifier_columns",
        "numeric_code_category_columns",
        "vector_blob_columns",
        "semantic_free_text_columns",
        "estimated_cardinality_columns",
        "average_profile_confidence",
        "high_confidence_columns",
        "medium_confidence_columns",
        "low_confidence_columns",
        "adaptive_warning_columns",
        "ucc_candidate_count",
        "ucc_unique_single_column_keys",
        "ucc_unique_composite_keys",
        "ucc_near_unique_candidates",
        "missing_value_rate",
        "baseline_error_rate",
        "rows_with_detector_errors",
        "runtime_seconds",
    ]

    # Convert the selected DataFrame into Markdown table text.
    table = markdown_table(frame[display_columns])

    # Find the datasets where Buckaroo detectors flagged the highest fraction
    # of sampled rows.
    high_error = frame.sort_values("baseline_error_rate", ascending=False).head(5)

    # Find datasets with the most natural-language text columns.  This is more
    # useful for SBERT planning than raw free_text_columns because vector blobs
    # are stored as text but are not semantically rich.
    text_rich = frame.sort_values("semantic_free_text_columns", ascending=False).head(5)

    # Find datasets with numeric-looking category codes.  These are the cases
    # the original profiler tended to misread as real measurements.
    code_rich = frame.sort_values("numeric_code_category_columns", ascending=False).head(5)

    # Find datasets with vector/blob columns such as pixels or embeddings.
    vector_rich = frame.sort_values("vector_blob_columns", ascending=False).head(5)

    # Find datasets with the highest missing-cell rate.
    missing_rich = frame.sort_values("missing_value_rate", ascending=False).head(5)

    # Build a Markdown report as a list of lines.  Later we join these lines
    # with newline characters.
    lines = [
        "# Dataset Shape Profile Report",
        "",
        "## Scope",
        f"- Dataset mode: {'multi-dataset' if args.multi_dataset else 'single dataset'}",
        f"- Profile rows per file: {args.profile_rows}",
        f"- Detector sample rows per file: {args.detector_rows}",
        "- Detector baseline: current Buckaroo anomaly, rare-value, missing-value, and type-mismatch detectors.",
        "- Distinct counting: exact for low-cardinality columns, HyperLogLog-style estimates for high-cardinality columns.",
        "- UCC discovery: HLL guides candidate selection, then bounded single/pair/triple key candidates are validated with exact tuple hashes.",
        "",
        "## Summary Table",
        table,
        "",
        "## Highest Baseline Error Rates",
        markdown_table(high_error[["dataset", "baseline_error_rate", "rows_with_detector_errors", "detector_sample_rows"]]),
        "",
        "## Most Text-Rich Datasets",
        markdown_table(
            text_rich[
                [
                    "dataset",
                    "semantic_free_text_columns",
                    "free_text_columns",
                    "vector_blob_columns",
                    "categorical_columns",
                    "numeric_columns",
                    "identifier_columns",
                ]
            ]
        ),
        "",
        "## Most Numeric-Code Category Datasets",
        markdown_table(
            code_rich[
                [
                    "dataset",
                    "numeric_code_category_columns",
                    "binary_category_columns",
                    "categorical_columns",
                    "numeric_columns",
                ]
            ]
        ),
        "",
        "## Most Vector/Blob-Like Datasets",
        markdown_table(
            vector_rich[
                [
                    "dataset",
                    "vector_blob_columns",
                    "semantic_free_text_columns",
                    "free_text_columns",
                    "total_columns",
                ]
            ]
        ),
        "",
        "## Highest Missingness",
        markdown_table(missing_rich[["dataset", "missing_value_rate", "total_rows", "total_columns"]]),
        "",
        "## Interpretation Notes",
        "- `total_rows` is the actual CSV row count loaded from disk.",
        "- `profiled_rows` controls column-role and missingness estimates, so these numbers are sample-based when the file is larger.",
        "- `baseline_error_rate` is rows with at least one detector error divided by detector-sampled rows.",
        "- A dataset can be large overall but still small for a specific detector if a column has few valid values or too many unique values relative to rows.",
        "- `numeric_code_category_columns` are numeric-looking fields that behave like category labels, such as gender 0/1 or ethnicity 0-4.",
        "- `vector_blob_columns` are long numeric-token strings, such as pixels or embeddings. They are text storage, but not natural-language text.",
        "- `semantic_free_text_columns` are the safer candidates for SBERT/text embeddings because vector blobs are excluded.",
        "- `estimated_cardinality_columns` counts columns where full-file distinct count used HyperLogLog instead of storing every unique value.",
        "- `average_profile_confidence` is Buckaroo's 0-1 trust score averaged across columns after considering sample size, parse quality, name hints, and uniqueness evidence.",
        "- `low_confidence_columns` are columns Buckaroo should explain carefully instead of treating the profile role as a hard fact.",
        "- `adaptive_warning_columns` are columns where Buckaroo found useful warnings, such as small-sample uniqueness risk or approximate distinct-count uncertainty.",
        "- `ucc_candidate_count` reports minimal unique or near-unique column combinations found by the bounded Buckaroo UCC Lite pass.",
        "- `ucc_unique_composite_keys` are multi-column keys, such as customer/date combinations, where no smaller unique subset was found.",
    ]

    # Join all report lines into one string and end with a newline.
    return "\n".join(lines) + "\n"


def markdown_table(frame: pd.DataFrame) -> str:
    """Format a small DataFrame as Markdown without optional dependencies."""
    # pandas has a built-in to_markdown(), but it needs the optional tabulate
    # package.  This helper avoids requiring extra installs.
    if frame.empty:
        return "_No rows._"

    # Convert column names to strings.
    columns = [str(column) for column in frame.columns]

    # Convert every cell value to text.
    rows = []
    for _, row in frame.iterrows():
        rows.append([str(row[column]) for column in frame.columns])

    # Markdown table header:
    #   | col1 | col2 |
    #   | --- | --- |
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]

    # Add one Markdown row per dataframe row.
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")

    # Return the whole table as one text block.
    return "\n".join(lines)


def main() -> None:
    # Read command-line options.
    args = parse_args()

    # Create the output folder if it does not exist.
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Decide which CSV files to profile.
    if args.multi_dataset:
        # Multi-dataset mode: every CSV file in the dataset directory.
        dataset_paths = sorted(args.dataset_dir.glob("*.csv"))
    else:
        # Single-dataset mode: only the chosen --dataset file.
        dataset_paths = [args.dataset]

    # results stores one dataset-level summary per CSV.
    results = []

    # column_frames stores detailed per-column profile tables.
    column_frames = []

    # ucc_frames stores one row per UCC/key candidate.
    ucc_frames = []

    # Run the experiment once per dataset.
    for dataset_path in dataset_paths:
        print(f"Profiling {dataset_path.name}...")

        # Profile one dataset.
        result, column_profile, ucc_frame = profile_dataset(
            dataset_path,
            args.profile_rows,
            args.detector_rows,
            args.cardinality_chunk_rows,
            args.ucc_max_arity,
            args.ucc_max_candidate_columns,
            args.ucc_near_unique_threshold,
        )

        # Save the dataset-level summary.
        results.append(result)

        # Save column-level details too, if there are any.
        if not column_profile.empty:
            column_profile = column_profile.copy()

            # Add the dataset name to every column-profile row so we know which
            # CSV each column came from after concatenating all datasets.
            column_profile.insert(0, "dataset", dataset_path.name)
            column_frames.append(column_profile)

        if not ucc_frame.empty:
            ucc_frame = ucc_frame.copy()
            ucc_frame.insert(0, "dataset", dataset_path.name)
            ucc_frames.append(ucc_frame)

    # Define output file paths.
    summary_path = args.out_dir / "dataset_shape_profiles.csv"
    columns_path = args.out_dir / "dataset_column_profiles.csv"
    ucc_path = args.out_dir / "dataset_ucc_candidates.csv"
    report_path = args.out_dir / "dataset_shape_profile_report.md"

    # Write one row per dataset.
    pd.DataFrame(results).to_csv(summary_path, index=False)

    # Write one row per column across all datasets.
    if column_frames:
        pd.concat(column_frames, ignore_index=True).to_csv(columns_path, index=False)
    else:
        # If no column frames exist, still create an empty CSV so downstream
        # code does not fail looking for the file.
        pd.DataFrame().to_csv(columns_path, index=False)

    # Write one row per minimal unique or near-unique key candidate.
    if ucc_frames:
        pd.concat(ucc_frames, ignore_index=True).to_csv(ucc_path, index=False)
    else:
        pd.DataFrame(
            columns=[
                "dataset",
                "columns",
                "arity",
                "uniqueness_ratio",
                "duplicate_count",
                "is_unique",
                "is_minimal",
                "confidence",
                "reason",
                "row_count",
                "unique_tuple_count",
                "missing_rows",
            ]
        ).to_csv(ucc_path, index=False)

    # Write the human-readable Markdown report.
    report_path.write_text(build_report(results, args), encoding="utf-8")

    # Print paths so the user knows where the outputs went.
    print(f"Wrote summary: {summary_path}")
    print(f"Wrote columns: {columns_path}")
    print(f"Wrote UCC candidates: {ucc_path}")
    print(f"Wrote report: {report_path}")


# Standard Python pattern: only run main() when this file is executed directly.
# If another file imports this script, main() will not run automatically.
if __name__ == "__main__":
    main()
