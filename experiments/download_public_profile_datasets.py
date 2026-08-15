"""Download public CSV datasets for Buckaroo profiler robustness tests.

The files are intentionally public, login-free CSVs.  The manifest includes
topic/source metadata so the sampling experiment can explain why each dataset
was included.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import urllib.request

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "outputs" / "public_profile_sampling_datasets"


DATASETS = [
    {
        "dataset_id": "titanic_passengers",
        "topic": "passenger survival / mixed categorical numeric",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/titanic.csv",
    },
    {
        "dataset_id": "diamonds_pricing",
        "topic": "retail product attributes / pricing",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/diamonds.csv",
    },
    {
        "dataset_id": "penguins_biology",
        "topic": "biology measurements / species categories",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/penguins.csv",
    },
    {
        "dataset_id": "monthly_airline_flights",
        "topic": "time series / airline passengers",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/flights.csv",
    },
    {
        "dataset_id": "restaurant_tips",
        "topic": "restaurant transactions / tips",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/tips.csv",
    },
    {
        "dataset_id": "planet_discoveries",
        "topic": "astronomy discoveries / sparse numeric fields",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/planets.csv",
    },
    {
        "dataset_id": "adult_census_income",
        "topic": "census demographics / income classification",
        "source_name": "Hugging Face scikit-learn adult census income",
        "source_url": "https://huggingface.co/datasets/scikit-learn/adult-census-income/resolve/main/adult.csv",
    },
    {
        "dataset_id": "bike_sharing_hourly",
        "topic": "transport demand / weather and hourly counts",
        "source_name": "justmarkham DAT8",
        "source_url": "https://raw.githubusercontent.com/justmarkham/DAT8/master/data/bikeshare.csv",
    },
    {
        "dataset_id": "wine_quality_red",
        "topic": "chemistry measurements / quality score",
        "source_name": "plotly datasets",
        "source_url": "https://raw.githubusercontent.com/plotly/datasets/master/winequality-red.csv",
    },
    {
        "dataset_id": "diabetes_health",
        "topic": "health measurements / diagnosis",
        "source_name": "plotly datasets",
        "source_url": "https://raw.githubusercontent.com/plotly/datasets/master/diabetes.csv",
    },
    {
        "dataset_id": "gapminder_countries",
        "topic": "country-year socioeconomic indicators",
        "source_name": "plotly datasets",
        "source_url": "https://raw.githubusercontent.com/plotly/datasets/master/gapminderDataFiveYear.csv",
    },
    {
        "dataset_id": "taxi_trips",
        "topic": "mobility trips / datetimes and payments",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/taxis.csv",
    },
    {
        "dataset_id": "auto_mpg",
        "topic": "vehicle measurements / model attributes",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/mpg.csv",
    },
    {
        "dataset_id": "fmri_neuroscience",
        "topic": "neuroscience repeated measures / subject ids",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/fmri.csv",
    },
    {
        "dataset_id": "sea_ice_extent",
        "topic": "climate time series / dates and numeric extent",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/seaice.csv",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download public CSV datasets for profiler experiments.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def download_file(url: str, destination: Path, *, force: bool) -> None:
    if destination.exists() and not force:
        return
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    destination.write_bytes(data)


def main() -> None:
    args = parse_args()
    dataset_dir = args.out_dir / "datasets"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for item in DATASETS:
        dataset_id = item["dataset_id"]
        csv_path = dataset_dir / f"{dataset_id}.csv"
        print(f"Downloading {dataset_id}...", flush=True)
        download_file(item["source_url"], csv_path, force=args.force)

        frame_head = pd.read_csv(csv_path, low_memory=False)
        rows.append(
            {
                **item,
                "local_path": str(csv_path),
                "row_count": int(len(frame_head)),
                "column_count": int(frame_head.shape[1]),
                "columns": "; ".join(str(column) for column in frame_head.columns),
                "file_size_bytes": int(csv_path.stat().st_size),
            }
        )

    manifest = pd.DataFrame(rows)
    manifest_path = args.out_dir / "dataset_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"Wrote manifest to {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
