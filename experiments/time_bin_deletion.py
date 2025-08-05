from experiments import lib
from pprint import pprint
import time
import pandas as pd
import random
import json
from tqdm import tqdm
from app.set_id_column import set_id_column
from postgres_wrangling import query
random.seed(0)
import math

table_name = 'adult'
x_column_name = 'age'
y_column_name = 'workclass'

# table_name = 'stackoverflow_db_uncleaned'
# x_column_name = 'ConvertedSalary'
# y_column_name = 'Continent'

# table_name = 'crimes'
# x_column_name = 'x coordinate'
# y_column_name = 'arrest'

file_name = f"results/{table_name}_runtimes_removal.json"

dataframe = pd.read_csv(f'./provided_datasets/{table_name}.csv')

max_rows = dataframe.shape[0]

# 10, 100, 1000, … up to the largest power-of-10 ≤ max_rows
row_count_list = [10 ** exp for exp in range(1, int(math.log10(max_rows)) + 1)]

# Always include the full dataset size (avoid a duplicate if it’s already a power of-10)
if row_count_list[-1] != max_rows:
    row_count_list.append(max_rows)

row_count_list[0] = 20

runtimes = {
    'pandas': {f"{row_count}":[] for row_count in row_count_list},
    'postgres': {f"{row_count}":[] for row_count in row_count_list}
    }
sample_count = 50

for row_count in tqdm(row_count_list):
    print(f"row count: {row_count}")
    lib.insert_dataframe_to_postgres(set_id_column(pd.read_csv(f'./provided_datasets/{table_name}.csv')).head(row_count), table_name)
    query.build_composite_index(table_name=table_name, column1=x_column_name, column2=y_column_name)
    for sample_idx in tqdm(range(sample_count)):
        start_time = time.time()
        histograms = lib.calculate_2D_histogram_postgres(x_column_name=x_column_name, y_column_name=y_column_name, table_name=table_name, max_row_count=1_000_000)
        error_bins = lib.get_all_clickable_bins(histograms)
        random_error_bin = random.choice(error_bins)
        # pprint(f"Table size: {lib.get_row_count(table_name=table_name)}")
        # pprint(random_error_bin)
        # exit(0)
        _, new_table_name = lib.remove_bad_data_postgres(random_error_bin, [x_column_name, y_column_name], table=table_name)

        # pprint(f"Table size: {lib.get_row_count(table_name=new_table_name)}")
        runtimes['postgres'][f"{row_count}"].append(time.time() - start_time)

        start_time = time.time()
        dataframe = lib.get_table_dataframe_from_postgres(table_name=table_name)
        histograms = lib.calculate_2D_histogram_pandas(dataframe=dataframe, x_column_name=x_column_name, y_column_name=y_column_name, max_row_count=1_000_000)
        error_bins = lib.get_all_clickable_bins(histograms=histograms)
        lib.remove_bad_data_pandas(currentSelection=random_error_bin, cols=[x_column_name, y_column_name], current_df=dataframe)
        runtimes['pandas'][f"{row_count}"].append(time.time() - start_time)

json.dump(runtimes, open(file_name, "w"), indent=4)
