from experiments import lib
import time, json, random
import pandas as pd
from tqdm import tqdm
from app.set_id_column import set_id_column
from postgres_wrangling import query
import math
random.seed(0)                           # reproducible sampling

table_name = 'adult'
x_column_name = 'age'
y_column_name = 'workclass'

# table_name      = "stackoverflow_db_uncleaned"
# x_column_name   = "ConvertedSalary"
# y_column_name   = "Continent"

# table_name = 'crimes___one_year_prior_to_present_20250421'
# x_column_name = 'x coordinate'
# y_column_name = 'arrest'

file_name = f"results/{table_name}_runtimes_imputation.json"

full_df = set_id_column(pd.read_csv(f"./provided_datasets/{table_name}.csv"))

max_rows = full_df.shape[0]

# 10, 100, 1000, … up to the largest power-of-10 ≤ max_rows
row_count_list = [10 ** exp for exp in range(1, int(math.log10(max_rows)) + 1)]

# Always include the full dataset size (avoid a duplicate if it’s already a power of-10)
if row_count_list[-1] != max_rows:
    row_count_list.append(max_rows)

row_count_list[0] = 20

sample_count   = 50

runtimes = {
    "pandas"  : {str(n): [] for n in row_count_list},
    "postgres": {str(n): [] for n in row_count_list},
}

for row_count in tqdm(row_count_list, desc="row-count"):
    print(f"row count: {row_count}")
    # ── 1. build a slice and inject 10 % missing values ────────────────
    df = full_df.head(row_count).copy()

    n_missing   = max(1, int(0.10 * len(df)))          # guarantee ≥1
    missing_idx = random.sample(range(len(df)), k=n_missing)

    for col in (x_column_name, y_column_name):
        df.loc[missing_idx, col] = pd.NA               # becomes SQL NULL

    # (re)create the table with this mutated slice
    lib.insert_dataframe_to_postgres(df, table_name)
    #           ↑ overwrite flag drops / truncates any previous copy
    query.build_composite_index(table_name=table_name, column1=x_column_name, column2=y_column_name)

    # ── 2. run the timing experiment ───────────────────────────────────
    for _ in tqdm(range(sample_count), leave=False):
        # -------- Postgres path --------
        start = time.time()

        histograms      = lib.calculate_2D_histogram_postgres(
            x_column_name=x_column_name,
            y_column_name=y_column_name,
            table_name=table_name,
            max_row_count=1_000_000,
        )
        error_bins      = lib.get_all_clickable_bins(histograms)
        random_error_bin = random.choice(error_bins)

        lib.impute_missing_data_postgres(
            random_error_bin, [x_column_name, y_column_name], table=table_name
        )

        runtimes["postgres"][str(row_count)].append(time.time() - start)

        # -------- Pandas path --------
        start = time.time()

        dataframe  = lib.get_table_dataframe_from_postgres(table_name=table_name)
        histograms = lib.calculate_2D_histogram_pandas(
            dataframe=dataframe,
            x_column_name=x_column_name,
            y_column_name=y_column_name,
            max_row_count=1_000_000,
        )
        error_bins = lib.get_all_clickable_bins(histograms)

        lib.impute_missing_data_pandas(
            currentSelection=random_error_bin,
            cols=[x_column_name, y_column_name],
            current_df=dataframe,
        )

        runtimes["pandas"][str(row_count)].append(time.time() - start)

# ── 3. persist the results ────────────────────────────────────────────
with open(file_name, "w") as f:
    json.dump(runtimes, f, indent=4)
