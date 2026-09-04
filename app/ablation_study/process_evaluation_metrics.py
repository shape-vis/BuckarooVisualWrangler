import json
import pandas as pd
import os
starting_path = os.getcwd() + os.sep + "app" + os.sep + "ablation_study" + os.sep

RESULTS_FILE = starting_path + os.sep + "combined_ablation_results.jsonl"

ABLATION_ORDER = [
    "baseline",
    "no_error_log",
    "no_data_profile",
    "no_action_log",
    "no_full_dataset",
    #"no_action_log_limit",
]

ABLATION_NAMES = {
    "baseline": "Baseline",
    "no_error_log": "Remove Error Log",
    "no_data_profile": "Remove Data Profile",
    "no_action_log": "Remove Action Log",
    "no_full_dataset": "Remove Full Dataset",
    "no_action_log_limit": "Remove Action Log Limit",
}

DATASET_ORDER = [
    "dirty_winequality-red",
    "dirty_global_air_pollution_dataset",
    "leading_causes_death",
    "disability_compensation",
]

DATASET_NAMES = {
    "dirty_winequality-red": "Red Wine Quality",
    "dirty_global_air_pollution_dataset": "BreathWatch",
    "leading_causes_death": "Leading Causes Death",
    "disability_compensation": "Disability Compensation",
}

def standard_reorder(table):

    table = table.reindex(
        index=ABLATION_ORDER,
        columns=DATASET_ORDER
    )

    return table

def create_dataset_info_latex_table(df, info_col):
    table_df = df.copy()
    table = table_df.pivot(
        index="ablation",
        columns="dataset",
        values=info_col
    )

    table["Average"] = table.mean(axis=1)
    latex_table = table.to_latex(
            float_format="%.2f",
            na_rep="",
            label=f"tab:{info_col}"
        )

    return latex_table


def create_percent_latex_table(df, column_name, percent_denom_col_name):
    #
    # curr_table = table.pivot(
    #     index="ablation",
    #     columns="dataset",
    #     values=f"percent_{column_name}"
    # )
    #
    # curr_table = curr_table.reindex(
    #     index=ABLATION_ORDER,
    #     columns=DATASET_ORDER
    # )
    #
    # curr_table["Average"] = curr_table.mean(axis=1)
    # curr_table.index = [
    #     ABLATION_NAMES.get(x, x)
    #     for x in curr_table.index
    # ]
    #
    # curr_table.columns = [
    #     DATASET_NAMES.get(x, x)
    #     for x in curr_table.columns
    # ]
    #
    # curr_table_latex = curr_table.to_latex(
    #         float_format="%.2f",
    #         na_rep="",
    #         label=f"tab:percent_{column_name}"
    #     )
    table_df = df.copy()

    table_df["percent_"+column_name] = (
        table_df[column_name] / table_df[percent_denom_col_name]
    ) * 100
    #print("TABLE_DF", table_df)


    table = table_df.pivot(
        index="ablation",
        columns="dataset",
        values="percent_"+column_name
    )

    table["Average"] = table.mean(axis=1)
    latex_table = table.to_latex(
            float_format="%.2f",
            na_rep="",
            label=f"tab:percent_{column_name}"
        )

    return latex_table


if __name__ == "__main__":
    results = []

    with open(RESULTS_FILE, "r") as f:
        for line in f:
            results.append(json.loads(line))

    results_df = pd.DataFrame(results)

    num_rows_initial_dataset_latex_table = create_dataset_info_latex_table(results_df, "num_rows_initial_dataset")
    print("NUM INITIAL DATASET ROWS", num_rows_initial_dataset_latex_table)

    num_rows_initial_dataset_latex_table = create_dataset_info_latex_table(results_df, "total_added_errors")
    print("TOTAL ADDED ERRORS", num_rows_initial_dataset_latex_table)

    num_rows_final_dataset_latex_table = create_dataset_info_latex_table(results_df, "num_rows_final_dataset")
    print("NUM FINAL DATASET ROWS", num_rows_final_dataset_latex_table)

    num_cols_latex_table = create_dataset_info_latex_table(results_df, "num_cols_initial_dataset")
    print("INITIAL DATASET COLS", num_cols_latex_table)

    total_action_counts_latex_table = create_dataset_info_latex_table(results_df, "total_action_count")
    print("TOTAL ACTION COUNT", total_action_counts_latex_table)

    # TODO: idk if this is right
    percent_total_removed_errors_latex_table = create_percent_latex_table(results_df, "total_removed_errors",
                                                                 "total_initial_dataset_errors")
    print("PERCENT TOTAL REMOVED ERRORS", percent_total_removed_errors_latex_table)

    percent_total_same_errors_latex_table = create_percent_latex_table(results_df, "total_same_errors",
                                                                 "total_final_dataset_errors")
    print("PERCENT TOTAL SAME ERRORS", percent_total_same_errors_latex_table)

    percent_total_added_errors_latex_table = create_percent_latex_table(results_df, "total_added_errors",
                                                                 "total_final_dataset_errors")
    print("PERCENT TOTAL ADDED ERRORS RELATIVE TO FINAL DATASET", percent_total_added_errors_latex_table)

    percent_total_added_errors_relative_to_initial_latex_table = create_percent_latex_table(results_df, "total_added_errors",
                                                                        "total_initial_dataset_errors")
    print("PERCENT TOTAL ADDED ERRORS RELATIVE TO INITIAL DATASET", percent_total_added_errors_relative_to_initial_latex_table)


    # TODO: fix this
    #percent_initial_errors_latex_table = create_percent_latex_table(results_df, "total_initial_dataset_errors","num_initial_data_points")

    #print("PERCENT INITIAL ERRORS", percent_initial_errors_latex_table)
    percent_final_errors_latex_table = create_percent_latex_table(results_df, "total_final_dataset_errors","num_final_data_points")
    print("PERCENT FINAL ERRORS", percent_final_errors_latex_table)

    percent_data_points_retained_latex_table = create_percent_latex_table(results_df, "num_final_data_points" ,"num_initial_data_points")
    print("PERCENT DATA POINTS RETAINED", percent_data_points_retained_latex_table)

    percent_redundant_actions_latex_table = create_percent_latex_table(results_df, "redundant_action_count", "total_action_count")
    print("PERCENT REDUNDANT ACTIONS", percent_redundant_actions_latex_table)

    percent_invalid_actions_latex_table = create_percent_latex_table(results_df, "total_invalid_action_count", "total_action_count")
    print("PERCENT INVALID ACTIONS", percent_invalid_actions_latex_table)

    percent_partial_failure_actions_latex_table = create_percent_latex_table(results_df, "total_partial_failure_action_count", "total_action_count")
    print("PERCENT PARTIAL FAILURE ACTIONS", percent_partial_failure_actions_latex_table)







