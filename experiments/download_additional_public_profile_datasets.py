"""Download a second batch of public CSV datasets for profiler robustness tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import urllib.request

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "outputs" / "public_profile_sampling_datasets_extra_15"


DATASETS = [
    {
        "dataset_id": "iris_species",
        "topic": "botany measurements / species labels",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/iris.csv",
    },
    {
        "dataset_id": "geyser_eruptions",
        "topic": "geology event durations / waiting times",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/geyser.csv",
    },
    {
        "dataset_id": "car_crashes_states",
        "topic": "traffic safety by US state / rates and insurance",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/car_crashes.csv",
    },
    {
        "dataset_id": "health_expenditure",
        "topic": "country-year health spending / life expectancy",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/healthexp.csv",
    },
    {
        "dataset_id": "dowjones_prices",
        "topic": "financial time series / dates and prices",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/dowjones.csv",
    },
    {
        "dataset_id": "exercise_pulse",
        "topic": "exercise experiment / repeated subject measurements",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/exercise.csv",
    },
    {
        "dataset_id": "attention_scores",
        "topic": "psychology experiment / subject scores",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/attention.csv",
    },
    {
        "dataset_id": "brain_networks",
        "topic": "neuroscience matrix-like features / many numeric columns",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/brain_networks.csv",
    },
    {
        "dataset_id": "visual_dots_neurons",
        "topic": "neuroscience stimulus response / firing rates",
        "source_name": "seaborn-data",
        "source_url": "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/dots.csv",
    },
    {
        "dataset_id": "stock_prices",
        "topic": "stock symbols / dated prices",
        "source_name": "vega-datasets",
        "source_url": "https://raw.githubusercontent.com/vega/vega-datasets/main/data/stocks.csv",
    },
    {
        "dataset_id": "us_airports",
        "topic": "airport reference table / geography and codes",
        "source_name": "vega-datasets",
        "source_url": "https://raw.githubusercontent.com/vega/vega-datasets/main/data/airports.csv",
    },
    {
        "dataset_id": "airport_traffic",
        "topic": "airport traffic / locations and passenger counts",
        "source_name": "plotly datasets",
        "source_url": "https://raw.githubusercontent.com/plotly/datasets/master/2011_february_us_airport_traffic.csv",
    },
    {
        "dataset_id": "usa_state_population",
        "topic": "US state population / ranked geographic table",
        "source_name": "plotly datasets",
        "source_url": "https://raw.githubusercontent.com/plotly/datasets/master/2014_usa_states.csv",
    },
    {
        "dataset_id": "boston_housing",
        "topic": "housing and neighborhood measurements",
        "source_name": "Rdatasets MASS",
        "source_url": "https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/MASS/Boston.csv",
    },
    {
        "dataset_id": "mammal_sleep",
        "topic": "animal sleep biology / mixed missingness",
        "source_name": "Rdatasets ggplot2",
        "source_url": "https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/ggplot2/msleep.csv",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download the second public CSV batch for profiler experiments.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def download_file(url: str, destination: Path, *, force: bool) -> None:
    if destination.exists() and not force:
        return
    with urllib.request.urlopen(url, timeout=60) as response:
        destination.write_bytes(response.read())


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
        frame = pd.read_csv(csv_path, low_memory=False)
        rows.append(
            {
                **item,
                "local_path": str(csv_path),
                "row_count": int(len(frame)),
                "column_count": int(frame.shape[1]),
                "columns": "; ".join(str(column) for column in frame.columns),
                "file_size_bytes": int(csv_path.stat().st_size),
            }
        )

    manifest = pd.DataFrame(rows)
    manifest_path = args.out_dir / "dataset_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"Wrote manifest to {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
