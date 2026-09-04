import pandas as pd
import os

from app.server_utils.service_helpers import create_error_df

starting_path = os.getcwd() + os.sep + "app" + os.sep + "ablation_study" + os.sep + "clean_datasets" + os.sep


DATASETS = [
    "winequality-red",
    "global_air_pollution_dataset",
]

for dataset in DATASETS:
    dataset_path = starting_path + dataset + ".csv"
    df = pd.read_csv(dataset_path)

    error_df = create_error_df(df)

    print(f"ERROR DF FOR DATASET {dataset}", error_df)


