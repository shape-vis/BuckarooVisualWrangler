"""Build the Buckaroo semantic-quality clustering benchmark.

The benchmark deliberately separates three kinds of evidence:

1. Real, unmodified datasets for blinded human semantic-similarity review.
2. Semi-synthetic datasets whose semantic cohorts come from real rows and whose
   injected quality problems have exact, private membership labels.
3. Shuffled-error controls that contain the same number and type of errors but
   remove the association between semantic meaning and data quality.

The production clustering implementation is not imported here. This prevents
the benchmark construction from silently depending on the method being tested.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "outputs" / "semantic_quality_clustering_benchmark_v1"
DEFAULT_CANONICAL_ROWS = 50_000
DEFAULT_CASE_ROWS = 10_000
DEFAULT_PAIRS_PER_DATASET = 12
DEFAULT_SEEDS = (1729, 2718, 3141)
DEFAULT_NOISE_LEVELS = (0.05, 0.10, 0.20)


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    partition: str
    topic: str
    structural_challenge: str
    source_name: str
    source_url: str
    license: str
    source_kind: str
    local_path: str | None = None
    archive_member: str | None = None
    delimiter: str = ","
    encoding: str = "utf-8"
    display_columns: tuple[str, ...] = ()
    pair_category_column: str | None = None
    pair_numeric_column: str | None = None


@dataclass(frozen=True)
class ConditionSpec:
    column: str
    operation: str
    value: str | float | None = None
    quantile: float | None = None


@dataclass(frozen=True)
class ScenarioSpec:
    dataset_id: str
    scenario_id: str
    semantic_label: str
    conditions: tuple[ConditionSpec, ...]
    error_column: str
    error_type: str


def nyc_311_url() -> str:
    params = {
        "$select": (
            "unique_key,created_date,closed_date,agency,complaint_type,descriptor,"
            "location_type,incident_zip,borough,status,resolution_description,latitude,longitude"
        ),
        "$where": "created_date between '2024-01-01T00:00:00' and '2024-01-31T23:59:59'",
        "$order": "unique_key",
        "$limit": "50000",
    }
    return "https://data.cityofnewyork.us/resource/erm2-nwe9.csv?" + urllib.parse.urlencode(params)


def chicago_food_url() -> str:
    params = {
        "$select": (
            "inspection_id,dba_name,aka_name,license_,facility_type,risk,city,state,zip,"
            "inspection_date,inspection_type,results,violations,latitude,longitude"
        ),
        "$where": "inspection_date between '2023-01-01T00:00:00' and '2023-12-31T23:59:59'",
        "$order": "inspection_id",
        "$limit": "50000",
    }
    return "https://data.cityofchicago.org/resource/4ijn-s7e5.csv?" + urllib.parse.urlencode(params)


def usgs_url() -> str:
    params = {
        "format": "csv",
        "starttime": "2023-01-01",
        "endtime": "2024-01-01",
        "minmagnitude": "2.5",
        "orderby": "time-asc",
        "limit": "20000",
    }
    return "https://earthquake.usgs.gov/fdsnws/event/1/query?" + urllib.parse.urlencode(params)


DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        "taxi_trips",
        "development",
        "mobility transactions",
        "mixed datetimes, categories, geography, and monetary measures",
        "seaborn-data",
        "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/taxis.csv",
        "BSD-3-Clause source repository",
        "local_csv",
        "outputs/public_profile_sampling_datasets/datasets/taxi_trips.csv",
        display_columns=("pickup", "dropoff", "distance", "fare", "total", "payment", "pickup_zone", "dropoff_zone"),
        pair_category_column="payment",
        pair_numeric_column="distance",
    ),
    DatasetSpec(
        "diamonds_pricing",
        "development",
        "retail product measurements",
        "continuous measurements with ordinal product attributes",
        "seaborn-data",
        "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/diamonds.csv",
        "BSD-3-Clause source repository",
        "local_csv",
        "outputs/public_profile_sampling_datasets/datasets/diamonds_pricing.csv",
        display_columns=("carat", "cut", "color", "clarity", "depth", "table", "price"),
        pair_category_column="cut",
        pair_numeric_column="carat",
    ),
    DatasetSpec(
        "adult_census_income",
        "development",
        "demographics and employment",
        "mixed categorical and numeric fields with sensitive semantics",
        "UCI Adult Census via Hugging Face",
        "https://huggingface.co/datasets/scikit-learn/adult-census-income/resolve/main/adult.csv",
        "Source dataset terms documented by UCI",
        "local_csv",
        "outputs/public_profile_sampling_datasets/datasets/adult_census_income.csv",
        display_columns=("age", "workclass", "education", "marital-status", "occupation", "hours-per-week", "native-country", "income"),
        pair_category_column="occupation",
        pair_numeric_column="hours-per-week",
    ),
    DatasetSpec(
        "us_airports",
        "development",
        "airport reference geography",
        "codes, place names, and coordinates with high uniqueness",
        "vega-datasets",
        "https://raw.githubusercontent.com/vega/vega-datasets/main/data/airports.csv",
        "BSD-3-Clause source repository",
        "local_csv",
        "outputs/public_profile_sampling_datasets_extra_15/datasets/us_airports.csv",
        display_columns=("iata", "name", "city", "state", "country", "latitude", "longitude"),
        pair_category_column="state",
        pair_numeric_column="latitude",
    ),
    DatasetSpec(
        "bank_marketing",
        "validation",
        "bank marketing interactions",
        "large mixed table with campaign, demographic, and outcome fields",
        "UCI Machine Learning Repository",
        "https://archive.ics.uci.edu/static/public/222/bank+marketing.zip",
        "CC BY 4.0",
        "zip_csv",
        archive_member="bank-full.csv",
        delimiter=";",
        display_columns=("age", "job", "marital", "education", "balance", "housing", "loan", "contact", "duration", "poutcome", "y"),
        pair_category_column="job",
        pair_numeric_column="balance",
    ),
    DatasetSpec(
        "seoul_bike_demand",
        "validation",
        "urban bike demand",
        "hourly lifecycle, weather, season, and demand measurements",
        "UCI Machine Learning Repository",
        "https://archive.ics.uci.edu/static/public/560/seoul+bike+sharing+demand.zip",
        "CC BY 4.0",
        "zip_csv",
        archive_member="SeoulBikeData.csv",
        encoding="cp1252",
        display_columns=("Date", "Rented Bike Count", "Hour", "Temperature", "Humidity", "Rainfall", "Seasons", "Holiday", "Functioning Day"),
        pair_category_column="Seasons",
        pair_numeric_column="Rented Bike Count",
    ),
    DatasetSpec(
        "nyc_311_requests",
        "validation",
        "municipal service requests",
        "operational text, lifecycle timestamps, location, and evolving categories",
        "NYC Open Data",
        nyc_311_url(),
        "NYC Open Data Terms of Use",
        "remote_csv",
        display_columns=("created_date", "closed_date", "agency", "complaint_type", "descriptor", "location_type", "borough", "status"),
        pair_category_column="complaint_type",
        pair_numeric_column="latitude",
    ),
    DatasetSpec(
        "usgs_earthquakes_2023",
        "validation",
        "earthquake events",
        "spatial coordinates, event time, magnitude, depth, and measurement quality",
        "USGS Earthquake Catalog",
        usgs_url(),
        "United States public-domain government data",
        "remote_csv",
        display_columns=("time", "place", "mag", "magType", "depth", "latitude", "longitude", "type", "status"),
        pair_category_column="type",
        pair_numeric_column="mag",
    ),
    DatasetSpec(
        "online_shoppers_intention",
        "locked_test",
        "e-commerce browsing sessions",
        "mixed behavioral measures and visitor, traffic, calendar, and purchase semantics",
        "UCI Machine Learning Repository",
        "https://archive.ics.uci.edu/static/public/468/online+shoppers+purchasing+intention+dataset.zip",
        "CC BY 4.0",
        "zip_csv",
        archive_member="online_shoppers_intention.csv",
        display_columns=(
            "Administrative",
            "ProductRelated",
            "ProductRelated_Duration",
            "BounceRates",
            "ExitRates",
            "PageValues",
            "Month",
            "VisitorType",
            "Weekend",
            "Revenue",
        ),
        pair_category_column="VisitorType",
        pair_numeric_column="PageValues",
    ),
    DatasetSpec(
        "appliances_energy",
        "locked_test",
        "building energy sensors",
        "dense multivariate time series with correlated sensor measurements",
        "UCI Machine Learning Repository",
        "https://archive.ics.uci.edu/static/public/374/appliances+energy+prediction.zip",
        "CC BY 4.0",
        "zip_csv",
        archive_member="energydata_complete.csv",
        display_columns=("date", "Appliances", "lights", "T1", "RH_1", "T_out", "Press_mm_hg", "Windspeed", "Visibility"),
        pair_category_column=None,
        pair_numeric_column="Appliances",
    ),
    DatasetSpec(
        "eshop_clickstream",
        "locked_test",
        "online shopping clickstream",
        "large sequential table with sessions, product categories, placement, and price",
        "UCI Machine Learning Repository",
        "https://archive.ics.uci.edu/static/public/553/clickstream+data+for+online+shopping.zip",
        "CC BY 4.0",
        "zip_csv",
        archive_member="e-shop clothing 2008.csv",
        delimiter=";",
        display_columns=("year", "month", "day", "order", "country", "session ID", "page 1", "page 2", "colour", "location", "price"),
        pair_category_column="page 1",
        pair_numeric_column="price",
    ),
    DatasetSpec(
        "chicago_food_inspections",
        "locked_test",
        "food safety inspections",
        "messy regulatory text, result categories, risk levels, lifecycle, and geography",
        "Chicago Open Data",
        chicago_food_url(),
        "City of Chicago Data Portal Terms of Use",
        "remote_csv",
        display_columns=("facility_type", "risk", "inspection_date", "inspection_type", "results", "violations", "city", "zip"),
        pair_category_column="results",
        pair_numeric_column="zip",
    ),
)


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        "taxi_trips",
        "long_card_trips",
        "long credit-card taxi trips",
        (ConditionSpec("payment", "equals", "credit card"), ConditionSpec("distance", "upper_quantile", quantile=0.75)),
        "total",
        "malformed_numeric",
    ),
    ScenarioSpec(
        "diamonds_pricing",
        "large_premium_diamonds",
        "large premium-cut diamonds",
        (ConditionSpec("cut", "equals", "Premium"), ConditionSpec("carat", "upper_quantile", quantile=0.75)),
        "clarity",
        "missing",
    ),
    ScenarioSpec(
        "adult_census_income",
        "long_hour_managerial_workers",
        "long-hour managerial workers",
        (ConditionSpec("occupation", "equals", "Exec-managerial"), ConditionSpec("hours-per-week", "upper_quantile", quantile=0.75)),
        "workclass",
        "missing",
    ),
    ScenarioSpec(
        "us_airports",
        "northern_us_airports",
        "northern United States airports",
        (ConditionSpec("country", "equals", "USA"), ConditionSpec("latitude", "upper_quantile", quantile=0.75)),
        "longitude",
        "invalid_coordinate",
    ),
    ScenarioSpec(
        "bank_marketing",
        "higher_balance_management_clients",
        "higher-balance management clients",
        (ConditionSpec("job", "equals", "management"), ConditionSpec("balance", "upper_quantile", quantile=0.75)),
        "contact",
        "rare_category",
    ),
    ScenarioSpec(
        "seoul_bike_demand",
        "high_demand_summer_hours",
        "high-demand summer bike hours",
        (ConditionSpec("Seasons", "equals", "Summer"), ConditionSpec("Rented Bike Count", "upper_quantile", quantile=0.75)),
        "Rainfall",
        "malformed_numeric",
    ),
    ScenarioSpec(
        "nyc_311_requests",
        "common_complaint_family",
        "the most prevalent NYC 311 complaint family",
        (ConditionSpec("complaint_type", "adaptive_common"),),
        "closed_date",
        "malformed_datetime",
    ),
    ScenarioSpec(
        "usgs_earthquakes_2023",
        "higher_magnitude_earthquakes",
        "higher-magnitude earthquake events",
        (ConditionSpec("type", "equals", "earthquake"), ConditionSpec("mag", "upper_quantile", quantile=0.75)),
        "depth",
        "malformed_numeric",
    ),
    ScenarioSpec(
        "online_shoppers_intention",
        "high_engagement_returning_sessions",
        "high-engagement sessions from returning visitors",
        (
            ConditionSpec("VisitorType", "equals", "Returning_Visitor"),
            ConditionSpec("ProductRelated_Duration", "upper_quantile", quantile=0.75),
        ),
        "PageValues",
        "malformed_numeric",
    ),
    ScenarioSpec(
        "appliances_energy",
        "high_energy_intervals",
        "high appliance-energy intervals",
        (ConditionSpec("Appliances", "upper_quantile", quantile=0.75),),
        "T1",
        "malformed_numeric",
    ),
    ScenarioSpec(
        "eshop_clickstream",
        "higher_price_common_category_clicks",
        "higher-priced clicks in a prevalent product category",
        (ConditionSpec("page 1", "adaptive_common"), ConditionSpec("price", "upper_quantile", quantile=0.75)),
        "colour",
        "rare_category",
    ),
    ScenarioSpec(
        "chicago_food_inspections",
        "failed_high_risk_inspections",
        "failed high-risk food inspections",
        (ConditionSpec("results", "equals", "Fail"), ConditionSpec("risk", "equals", "Risk 1 (High)")),
        "violations",
        "missing",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the semantic-quality clustering benchmark.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--canonical-rows", type=int, default=DEFAULT_CANONICAL_ROWS)
    parser.add_argument("--case-rows", type=int, default=DEFAULT_CASE_ROWS)
    parser.add_argument("--pairs-per-dataset", type=int, default=DEFAULT_PAIRS_PER_DATASET)
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--dataset", action="append", dest="datasets", help="Build only the named dataset; repeatable.")
    parser.add_argument("--skip-semi-synthetic", action="store_true")
    return parser.parse_args()


def stable_seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def resolve_column(frame: pd.DataFrame, requested: str | None) -> str | None:
    if requested is None:
        return None
    target = normalized_name(requested)
    exact = [column for column in frame.columns if normalized_name(column) == target]
    if exact:
        return str(exact[0])
    contains = [column for column in frame.columns if target and target in normalized_name(column)]
    return str(contains[0]) if len(contains) == 1 else None


def unique_columns(columns: Iterable[Any]) -> list[str]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for raw in columns:
        base = str(raw).strip() or "unnamed_column"
        count = counts.get(base, 0)
        counts[base] = count + 1
        result.append(base if count == 0 else f"{base}_{count + 1}")
    return result


def download(url: str, destination: Path, *, force: bool) -> Path:
    if destination.exists() and not force:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "BuckarooResearchBenchmark/1.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        destination.write_bytes(response.read())
    return destination


def archive_suffix(spec: DatasetSpec) -> str:
    if spec.source_kind.startswith("zip_"):
        return ".zip"
    return ".csv"


def find_archive_member(archive: zipfile.ZipFile, requested: str | None) -> str:
    candidates = [name for name in archive.namelist() if not name.endswith("/")]
    if requested:
        target = normalized_name(Path(requested).name)
        matches = [name for name in candidates if normalized_name(Path(name).name) == target]
        if not matches:
            matches = [name for name in candidates if target in normalized_name(Path(name).name)]
        if matches:
            return sorted(matches, key=len)[0]
    data_members = [name for name in candidates if Path(name).suffix.lower() in {".csv", ".xlsx", ".xls"}]
    if not data_members:
        raise ValueError(f"No CSV or Excel data member found in archive: {candidates}")
    return sorted(data_members, key=len)[0]


def extract_archive_data(
    archive_source: Path | io.BytesIO,
    requested: str | None,
    *,
    allow_fallback: bool = True,
    depth: int = 0,
) -> tuple[bytes, str]:
    """Find a requested data file, including inside nested ZIP archives."""
    if depth > 3:
        raise ValueError("Archive nesting exceeds the supported depth of 3")

    with zipfile.ZipFile(archive_source) as archive:
        candidates = [name for name in archive.namelist() if not name.endswith("/")]
        if requested:
            target = normalized_name(Path(requested).name)
            matches = [name for name in candidates if normalized_name(Path(name).name) == target]
            if not matches:
                matches = [name for name in candidates if target in normalized_name(Path(name).name)]
            if matches:
                member = sorted(matches, key=len)[0]
                return archive.read(member), member

        nested_archives = [name for name in candidates if Path(name).suffix.lower() == ".zip"]
        for nested_name in nested_archives:
            try:
                data, member = extract_archive_data(
                    io.BytesIO(archive.read(nested_name)),
                    requested,
                    allow_fallback=False,
                    depth=depth + 1,
                )
                return data, f"{nested_name}!{member}"
            except ValueError:
                continue

        if allow_fallback:
            data_members = [
                name for name in candidates if Path(name).suffix.lower() in {".csv", ".xlsx", ".xls"}
            ]
            if data_members:
                member = sorted(data_members, key=len)[0]
                return archive.read(member), member
            for nested_name in nested_archives:
                try:
                    data, member = extract_archive_data(
                        io.BytesIO(archive.read(nested_name)),
                        None,
                        allow_fallback=True,
                        depth=depth + 1,
                    )
                    return data, f"{nested_name}!{member}"
                except ValueError:
                    continue

    raise ValueError(f"No matching CSV or Excel data member found for {requested!r}")


def read_csv_bytes(data: bytes, spec: DatasetSpec) -> pd.DataFrame:
    encodings = [spec.encoding, "utf-8-sig", "cp1252", "latin1"]
    last_error: Exception | None = None
    for encoding in dict.fromkeys(encodings):
        try:
            text = data.decode(encoding)
            return pd.read_csv(io.StringIO(text), sep=spec.delimiter, low_memory=False)
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise ValueError(f"Could not parse CSV for {spec.dataset_id}: {last_error}")


def load_source_frame(spec: DatasetSpec, raw_dir: Path, *, force_download: bool) -> tuple[pd.DataFrame, Path]:
    if spec.source_kind == "local_csv":
        source = ROOT / str(spec.local_path)
        if not source.exists():
            raise FileNotFoundError(f"Missing local source for {spec.dataset_id}: {source}")
        return pd.read_csv(source, low_memory=False), source

    raw_path = raw_dir / f"{spec.dataset_id}{archive_suffix(spec)}"
    download(spec.source_url, raw_path, force=force_download)
    if spec.source_kind == "remote_csv":
        return pd.read_csv(raw_path, low_memory=False), raw_path

    data, _member = extract_archive_data(raw_path, spec.archive_member)
    if spec.source_kind == "zip_csv":
        return read_csv_bytes(data, spec), raw_path
    if spec.source_kind == "zip_excel":
        return pd.read_excel(io.BytesIO(data)), raw_path
    raise ValueError(f"Unsupported source kind: {spec.source_kind}")


def canonicalize_frame(frame: pd.DataFrame, dataset_id: str, max_rows: int) -> tuple[pd.DataFrame, int]:
    source_rows = len(frame)
    frame = frame.copy()
    frame.columns = unique_columns(frame.columns)
    frame = frame.dropna(axis=1, how="all")
    if len(frame) > max_rows:
        frame = frame.sample(n=max_rows, random_state=stable_seed(f"canonical:{dataset_id}"), replace=False)
    frame = frame.reset_index().rename(columns={"index": "source_row_number"})
    frame.insert(
        0,
        "benchmark_row_id",
        [f"{dataset_id}:{int(value)}" for value in frame["source_row_number"].tolist()],
    )
    return frame, source_rows


def select_display_columns(frame: pd.DataFrame, requested: Iterable[str]) -> list[str]:
    columns = []
    for name in requested:
        resolved = resolve_column(frame, name)
        if resolved and resolved not in columns:
            columns.append(resolved)
    if not columns:
        columns = [column for column in frame.columns if column not in {"benchmark_row_id", "source_row_number"}][:8]
    return columns[:10]


def auto_category_column(frame: pd.DataFrame) -> str | None:
    candidates = []
    for column in frame.columns:
        if column in {"benchmark_row_id", "source_row_number"}:
            continue
        values = frame[column].dropna()
        unique = values.nunique()
        if 2 <= unique <= min(100, max(2, len(values) // 3)):
            numeric_ratio = pd.to_numeric(values, errors="coerce").notna().mean()
            if numeric_ratio < 0.95:
                candidates.append((abs(0.5 - min(0.5, unique / max(1, len(values)))), column))
    return str(sorted(candidates)[0][1]) if candidates else None


def auto_numeric_column(frame: pd.DataFrame) -> str | None:
    candidates = []
    for column in frame.columns:
        if column in {"benchmark_row_id", "source_row_number"}:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        ratio = numeric.notna().mean()
        if ratio >= 0.90 and numeric.nunique() >= 8:
            candidates.append((numeric.nunique(), column))
    return str(sorted(candidates, reverse=True)[0][1]) if candidates else None


def quantile_codes(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    try:
        return pd.qcut(numeric, q=4, labels=False, duplicates="drop").astype("Int64")
    except (ValueError, TypeError):
        return pd.Series(pd.array([pd.NA] * len(series), dtype="Int64"), index=series.index)


def row_summary(row: pd.Series, columns: list[str], max_chars: int = 1000) -> str:
    parts = []
    for column in columns:
        value = row.get(column)
        rendered = "<missing>" if pd.isna(value) else str(value).replace("\n", " ").strip()
        if len(rendered) > 180:
            rendered = rendered[:177] + "..."
        parts.append(f"{column}={rendered}")
    text = " | ".join(parts)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def generate_pairwise_tasks(
    frame: pd.DataFrame,
    spec: DatasetSpec,
    pairs_per_dataset: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    display_columns = select_display_columns(frame, spec.display_columns)
    category = resolve_column(frame, spec.pair_category_column) or auto_category_column(frame)
    numeric = resolve_column(frame, spec.pair_numeric_column) or auto_numeric_column(frame)
    rng = np.random.default_rng(stable_seed(f"pairs:{spec.dataset_id}"))
    working = frame.copy()
    working["_category"] = (
        working[category].astype("string").fillna("<missing>").str.strip().str.lower()
        if category
        else "<none>"
    )
    working["_quartile"] = quantile_codes(working[numeric]) if numeric else pd.Series(0, index=working.index)

    target_each = max(1, pairs_per_dataset // 3)
    selected: list[tuple[int, int, str]] = []
    used: set[tuple[int, int]] = set()

    def add_pair(left: int, right: int, source: str) -> bool:
        if left == right:
            return False
        key = tuple(sorted((int(left), int(right))))
        if key in used:
            return False
        used.add(key)
        selected.append((key[0], key[1], source))
        return True

    grouped = working.groupby(["_category", "_quartile"], dropna=False).groups
    eligible = [np.asarray(indexes, dtype=int) for indexes in grouped.values() if len(indexes) >= 2]
    rng.shuffle(eligible)
    for indexes in eligible:
        if sum(source == "candidate_similar" for *_pair, source in selected) >= target_each:
            break
        choice = rng.choice(indexes, size=2, replace=False)
        add_pair(int(choice[0]), int(choice[1]), "candidate_similar")

    attempts = 0
    while sum(source == "candidate_contrast" for *_pair, source in selected) < target_each and attempts < 5000:
        attempts += 1
        left, right = rng.choice(len(working), size=2, replace=False)
        left_row, right_row = working.iloc[int(left)], working.iloc[int(right)]
        category_diff = left_row["_category"] != right_row["_category"]
        quartile_diff = (
            pd.notna(left_row["_quartile"])
            and pd.notna(right_row["_quartile"])
            and abs(int(left_row["_quartile"]) - int(right_row["_quartile"])) >= 2
        )
        if category_diff or quartile_diff:
            add_pair(int(left), int(right), "candidate_contrast")

    while len(selected) < pairs_per_dataset:
        left, right = rng.choice(len(working), size=2, replace=False)
        add_pair(int(left), int(right), "random")

    tasks, audit = [], []
    order = rng.permutation(len(selected))
    for visible_number, position in enumerate(order, start=1):
        left_index, right_index, source = selected[int(position)]
        left, right = frame.iloc[left_index], frame.iloc[right_index]
        task_id = f"PAIR-{spec.dataset_id}-{visible_number:03d}"
        tasks.append(
            {
                "task_id": task_id,
                "dataset_id": spec.dataset_id,
                "partition": spec.partition,
                "row_a": row_summary(left, display_columns),
                "row_b": row_summary(right, display_columns),
                "semantic_similarity_1_to_5": "",
                "same_useful_group": "",
                "important_matching_or_conflicting_fields": "",
                "reviewer_confidence_1_to_5": "",
                "reviewer_id": "",
                "review_status": "not_started",
                "notes": "",
            }
        )
        audit.append(
            {
                "task_id": task_id,
                "dataset_id": spec.dataset_id,
                "sampling_stratum": source,
                "category_column_used": category or "",
                "numeric_column_used": numeric or "",
                "row_a_id": left["benchmark_row_id"],
                "row_b_id": right["benchmark_row_id"],
            }
        )
    return tasks, audit


def condition_mask(frame: pd.DataFrame, condition: ConditionSpec) -> tuple[pd.Series, dict[str, Any]]:
    column = resolve_column(frame, condition.column)
    if not column:
        raise KeyError(f"Could not resolve condition column {condition.column!r}")
    series = frame[column]
    details: dict[str, Any] = {"column": column, "operation": condition.operation}
    if condition.operation == "equals":
        expected = str(condition.value).strip().lower()
        mask = series.astype("string").str.strip().str.lower().eq(expected).fillna(False)
        details["selected_value"] = condition.value
        return mask, details
    if condition.operation == "adaptive_common":
        values = series.astype("string").str.strip().replace({"": pd.NA}).dropna()
        counts = values.value_counts()
        if counts.empty:
            raise ValueError(f"No non-missing values in {column}")
        proportions = counts / counts.sum()
        # Select the category that makes the most balanced data-derived split.
        selected = sorted(proportions.items(), key=lambda item: (abs(float(item[1]) - 0.5), str(item[0])))[0][0]
        mask = series.astype("string").str.strip().eq(str(selected)).fillna(False)
        details["selected_value"] = selected
        details["selected_prevalence"] = float(mask.mean())
        return mask, details
    if condition.operation in {"upper_quantile", "lower_quantile"}:
        numeric = pd.to_numeric(series, errors="coerce")
        quantile = float(condition.quantile if condition.quantile is not None else 0.75)
        boundary = float(numeric.quantile(quantile))
        mask = numeric.ge(boundary) if condition.operation == "upper_quantile" else numeric.le(boundary)
        details.update({"quantile": quantile, "boundary": boundary})
        return mask.fillna(False), details
    raise ValueError(f"Unsupported condition operation: {condition.operation}")


def semantic_cohort(frame: pd.DataFrame, scenario: ScenarioSpec) -> tuple[pd.Series, list[dict[str, Any]]]:
    masks, details = [], []
    for condition in scenario.conditions:
        mask, condition_details = condition_mask(frame, condition)
        masks.append(mask)
        details.append(condition_details)
    combined = pd.Series(True, index=frame.index)
    for mask in masks:
        combined &= mask
    minimum_support = max(25, int(math.ceil(math.sqrt(len(frame)))))
    if int(combined.sum()) < minimum_support and len(masks) > 1:
        # Relax only the last condition and record the relaxation. This avoids
        # manufacturing a tiny target that no clustering method could recover.
        combined = masks[0].copy()
        details.append(
            {
                "operation": "adaptive_relaxation",
                "reason": "combined cohort below sqrt(n) support",
                "minimum_support": minimum_support,
                "retained_condition_count": 1,
            }
        )
    if int(combined.sum()) < 2:
        raise ValueError(f"Scenario {scenario.scenario_id} produced fewer than two cohort rows")
    return combined, details


def injected_value(series: pd.Series, error_type: str) -> Any:
    if error_type == "missing":
        return np.nan
    if error_type == "malformed_numeric":
        return "not_a_number"
    if error_type == "malformed_datetime":
        return "not-a-date"
    if error_type == "rare_category":
        existing = {str(value) for value in series.dropna().astype(str).tolist()}
        candidate = "__UNEXPECTED_CATEGORY__"
        while candidate in existing:
            candidate = "_" + candidate
        return candidate
    if error_type == "invalid_coordinate":
        return 999.0
    raise ValueError(f"Unsupported error type: {error_type}")


def private_case_id(dataset_id: str, scenario_id: str, association: str, seed: int, noise: float) -> str:
    key = f"{dataset_id}|{scenario_id}|{association}|{seed}|{noise:.4f}"
    return "CASE-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12].upper()


def build_semi_synthetic_cases(
    frame: pd.DataFrame,
    spec: DatasetSpec,
    scenario: ScenarioSpec,
    out_dir: Path,
    case_rows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dataset_dir = out_dir / "semi_synthetic" / spec.partition / spec.dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=True)
    case_manifest: list[dict[str, Any]] = []
    membership_rows: list[dict[str, Any]] = []
    injection_rows: list[dict[str, Any]] = []

    for seed in DEFAULT_SEEDS:
        base = frame
        if len(base) > case_rows:
            base = base.sample(n=case_rows, random_state=seed, replace=False)
        base = base.reset_index(drop=True)
        cohort_mask, condition_details = semantic_cohort(base, scenario)
        cohort_positions = np.flatnonzero(cohort_mask.to_numpy())
        all_positions = np.arange(len(base))
        rng = np.random.default_rng(seed)
        correlated_order = rng.permutation(cohort_positions)
        shuffled_order = rng.permutation(all_positions)
        error_column = resolve_column(base, scenario.error_column)
        if not error_column:
            raise KeyError(f"Could not resolve error column {scenario.error_column!r} in {spec.dataset_id}")
        replacement = injected_value(base[error_column], scenario.error_type)

        for association, order in (("correlated", correlated_order), ("shuffled_control", shuffled_order)):
            for noise_level in DEFAULT_NOISE_LEVELS:
                injection_count = max(1, int(round(noise_level * len(cohort_positions))))
                injection_count = min(injection_count, len(order))
                selected_positions = np.asarray(order[:injection_count], dtype=int)
                selected_set = set(int(value) for value in selected_positions.tolist())
                case = base.copy()
                originals = case.iloc[selected_positions][error_column].tolist()
                # Planted corruptions deliberately cross physical types (for example,
                # "not_a_number" in a float column), so make that mixed dtype explicit.
                case[error_column] = case[error_column].astype("object")
                case.loc[selected_positions, error_column] = replacement
                case_id = private_case_id(spec.dataset_id, scenario.scenario_id, association, seed, noise_level)
                case_path = dataset_dir / f"{case_id}.csv"
                case.to_csv(case_path, index=False)

                joint_count = 0
                for position, row_id in enumerate(case["benchmark_row_id"].tolist()):
                    is_semantic = bool(cohort_mask.iloc[position])
                    is_injected = position in selected_set
                    is_joint = is_semantic and is_injected
                    joint_count += int(is_joint)
                    membership_rows.append(
                        {
                            "case_id": case_id,
                            "dataset_id": spec.dataset_id,
                            "partition": spec.partition,
                            "benchmark_row_id": row_id,
                            "semantic_group_id": scenario.scenario_id if is_semantic else "",
                            "quality_pattern_id": scenario.error_type if is_injected else "",
                            "joint_target_id": f"{scenario.scenario_id}+{scenario.error_type}" if is_joint else "",
                            "is_semantic_cohort": int(is_semantic),
                            "is_injected_error": int(is_injected),
                            "is_joint_target": int(is_joint),
                        }
                    )
                for offset, position in enumerate(selected_positions.tolist()):
                    injection_rows.append(
                        {
                            "case_id": case_id,
                            "dataset_id": spec.dataset_id,
                            "benchmark_row_id": case.iloc[position]["benchmark_row_id"],
                            "column": error_column,
                            "error_type": scenario.error_type,
                            "original_value": "<missing>" if pd.isna(originals[offset]) else str(originals[offset]),
                            "injected_value": "<missing>" if pd.isna(replacement) else str(replacement),
                        }
                    )

                case_manifest.append(
                    {
                        "case_id": case_id,
                        "dataset_id": spec.dataset_id,
                        "partition": spec.partition,
                        "scenario_id": scenario.scenario_id,
                        "semantic_label": scenario.semantic_label,
                        "association_mode": association,
                        "seed": seed,
                        "noise_level_within_semantic_cohort": noise_level,
                        "row_count": len(case),
                        "semantic_cohort_rows": int(cohort_mask.sum()),
                        "injected_error_rows": len(selected_positions),
                        "joint_target_rows": joint_count,
                        "error_column": error_column,
                        "error_type": scenario.error_type,
                        "condition_details_json": json.dumps(condition_details, sort_keys=True, default=str),
                        "relative_path": str(case_path.relative_to(out_dir)),
                        "sha256": sha256_file(case_path),
                    }
                )
    return case_manifest, membership_rows, injection_rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def validate_build(
    specs: list[DatasetSpec],
    manifest_rows: list[dict[str, Any]],
    pair_tasks: list[dict[str, Any]],
    pair_audit: list[dict[str, Any]],
    case_manifest: list[dict[str, Any]],
    membership_rows: list[dict[str, Any]],
    injection_rows: list[dict[str, Any]],
    *,
    pairs_per_dataset: int,
) -> None:
    """Fail the build if blinding, pairing, provenance, or labels drift."""
    if len(manifest_rows) != len(specs):
        raise ValueError("Dataset manifest does not contain exactly one row per selected dataset")
    dataset_ids = [row["dataset_id"] for row in manifest_rows]
    if len(dataset_ids) != len(set(dataset_ids)):
        raise ValueError("Dataset IDs are not unique")
    for row in manifest_rows:
        if len(str(row.get("raw_source_sha256", ""))) != 64:
            raise ValueError(f"Missing raw-source hash for {row['dataset_id']}")
        if len(str(row.get("canonical_sha256", ""))) != 64:
            raise ValueError(f"Missing canonical hash for {row['dataset_id']}")

    expected_tasks = len(specs) * pairs_per_dataset
    if len(pair_tasks) != expected_tasks or len(pair_audit) != expected_tasks:
        raise ValueError("Pairwise task or private sampling-audit count is incorrect")
    public_task_ids = [row["task_id"] for row in pair_tasks]
    audit_task_ids = [row["task_id"] for row in pair_audit]
    if len(public_task_ids) != len(set(public_task_ids)) or set(public_task_ids) != set(audit_task_ids):
        raise ValueError("Pairwise task IDs are duplicated or do not match the private audit")
    private_tokens = {"sampling_stratum", "association_mode", "injected", "ground_truth"}
    leaked_columns = {
        column
        for task in pair_tasks
        for column in task
        if any(token in column.lower() for token in private_tokens)
    }
    if leaked_columns:
        raise ValueError(f"Private fields leaked into blinded tasks: {sorted(leaked_columns)}")

    if not case_manifest:
        if membership_rows or injection_rows:
            raise ValueError("Ground-truth rows exist without semi-synthetic cases")
        return

    cases = pd.DataFrame(case_manifest)
    if cases["case_id"].duplicated().any():
        raise ValueError("Semi-synthetic case IDs are not unique")
    if not cases["semantic_cohort_rows"].gt(0).all():
        raise ValueError("At least one planted semantic cohort is empty")
    if not cases["injected_error_rows"].gt(0).all():
        raise ValueError("At least one semi-synthetic case has no planted errors")
    paired = cases.groupby(["dataset_id", "seed", "noise_level_within_semantic_cohort"])
    if not paired["association_mode"].nunique().eq(2).all():
        raise ValueError("Every planted case must have correlated and shuffled-control variants")
    if not paired["injected_error_rows"].nunique().eq(1).all():
        raise ValueError("Correlated and shuffled controls must preserve the same error count")
    if len(membership_rows) != int(cases["row_count"].sum()):
        raise ValueError("Row-membership ground truth does not cover every case row exactly once")
    if len(injection_rows) != int(cases["injected_error_rows"].sum()):
        raise ValueError("Injection log count does not match the planted-error totals")
    case_ids = set(cases["case_id"])
    if {row["case_id"] for row in membership_rows} != case_ids:
        raise ValueError("Membership ground truth is missing one or more case IDs")
    if {row["case_id"] for row in injection_rows} != case_ids:
        raise ValueError("Injection log is missing one or more case IDs")


def build_benchmark(args: argparse.Namespace) -> None:
    out_dir: Path = args.out_dir.resolve()
    raw_dir = out_dir / "raw_sources"
    canonical_dir = out_dir / "canonical_real_datasets"
    private_dir = out_dir / "private_ground_truth"
    human_dir = out_dir / "human_review"
    for directory in (raw_dir, canonical_dir, private_dir, human_dir):
        directory.mkdir(parents=True, exist_ok=True)

    selected_ids = set(args.datasets or [])
    specs = [spec for spec in DATASETS if not selected_ids or spec.dataset_id in selected_ids]
    unknown = selected_ids - {spec.dataset_id for spec in DATASETS}
    if unknown:
        raise ValueError(f"Unknown dataset IDs: {sorted(unknown)}")

    scenario_map = {scenario.dataset_id: scenario for scenario in SCENARIOS}
    manifest_rows: list[dict[str, Any]] = []
    pair_tasks: list[dict[str, Any]] = []
    pair_audit: list[dict[str, Any]] = []
    case_manifest: list[dict[str, Any]] = []
    membership_rows: list[dict[str, Any]] = []
    injection_rows: list[dict[str, Any]] = []

    for spec in specs:
        print(f"Loading {spec.dataset_id} ({spec.partition})...", flush=True)
        source_frame, raw_path = load_source_frame(spec, raw_dir, force_download=args.force_download)
        canonical, source_rows = canonicalize_frame(source_frame, spec.dataset_id, args.canonical_rows)
        canonical_path = canonical_dir / f"{spec.dataset_id}.csv"
        canonical.to_csv(canonical_path, index=False)
        tasks, audits = generate_pairwise_tasks(canonical, spec, args.pairs_per_dataset)
        pair_tasks.extend(tasks)
        pair_audit.extend(audits)
        manifest_rows.append(
            {
                **asdict(spec),
                "local_path": str(canonical_path.relative_to(out_dir)),
                "raw_cache_path": str(raw_path),
                "raw_source_bytes": raw_path.stat().st_size,
                "raw_source_sha256": sha256_file(raw_path),
                "source_row_count": source_rows,
                "canonical_row_count": len(canonical),
                "column_count": canonical.shape[1] - 2,
                "columns": "; ".join(column for column in canonical.columns if column not in {"benchmark_row_id", "source_row_number"}),
                "canonical_sha256": sha256_file(canonical_path),
                "canonical_bytes": canonical_path.stat().st_size,
                "pairwise_review_tasks": len(tasks),
            }
        )
        if not args.skip_semi_synthetic and spec.dataset_id in scenario_map:
            cases, memberships, injections = build_semi_synthetic_cases(
                canonical,
                spec,
                scenario_map[spec.dataset_id],
                out_dir,
                args.case_rows,
            )
            case_manifest.extend(cases)
            membership_rows.extend(memberships)
            injection_rows.extend(injections)

    validate_build(
        specs,
        manifest_rows,
        pair_tasks,
        pair_audit,
        case_manifest,
        membership_rows,
        injection_rows,
        pairs_per_dataset=args.pairs_per_dataset,
    )
    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(out_dir / "dataset_manifest.csv", index=False)
    pd.DataFrame(pair_tasks).to_csv(human_dir / "pairwise_review_tasks_BLINDED.csv", index=False)
    pd.DataFrame(pair_audit).to_csv(private_dir / "pairwise_task_sampling_audit.csv", index=False)
    if case_manifest:
        pd.DataFrame(case_manifest).to_csv(out_dir / "semi_synthetic_case_manifest.csv", index=False)
        pd.DataFrame(membership_rows).to_csv(private_dir / "semi_synthetic_membership_ground_truth.csv", index=False)
        pd.DataFrame(injection_rows).to_csv(private_dir / "semi_synthetic_injection_log.csv", index=False)

    frozen_config = {
        "benchmark_version": "1.0.0",
        "canonical_row_cap": args.canonical_rows,
        "semi_synthetic_case_row_cap": args.case_rows,
        "pairwise_tasks_per_dataset": args.pairs_per_dataset,
        "seeds": list(DEFAULT_SEEDS),
        "noise_levels_within_semantic_cohort": list(DEFAULT_NOISE_LEVELS),
        "datasets": [asdict(spec) for spec in specs],
        "scenarios": [asdict(scenario_map[spec.dataset_id]) for spec in specs if spec.dataset_id in scenario_map],
    }
    write_json(out_dir / "benchmark_config_frozen.json", frozen_config)
    summary = {
        "dataset_count": len(manifest_rows),
        "partitions": manifest["partition"].value_counts().to_dict() if not manifest.empty else {},
        "pairwise_review_task_count": len(pair_tasks),
        "semi_synthetic_case_count": len(case_manifest),
        "membership_ground_truth_rows": len(membership_rows),
        "injection_log_rows": len(injection_rows),
    }
    write_json(out_dir / "benchmark_build_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


def main() -> None:
    build_benchmark(parse_args())


if __name__ == "__main__":
    main()
