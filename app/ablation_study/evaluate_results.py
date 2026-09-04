import json
import csv
import os
import itertools
import sys
import pandas as pd

from app.server_utils.service_helpers import create_error_df

if len(sys.argv) < 5:
    print("usage: python evaluate_results.py action_log_path.csv final_dataset_path.csv initial_dataset_path.csv")

# Returns list of all row and col pairs that were affected by the llm action
# TODO: check if this is right
def get_all_affected_positions(rows, column):
    affected_positions = list(itertools.product(rows, column))

    return affected_positions

def condense_error_df(error_df):
    # Gather anomaly rows
    condensed_error_dict = {}
    for error_type in ["anomaly", "missing", "incomplete", "mismatch"]:
        curr_error_type_df = error_df[error_df["error_type"] == error_type]

        #print("CONDENSED ERROR DICT:", condensed_error_dict)
        # List of tuples of each location of the error_type
        condensed_error_dict[error_type] =  list(zip(list(curr_error_type_df["row_id"]), list(curr_error_type_df["column_id"])))

    return condensed_error_dict

import json
from datetime import datetime


starting_path = os.getcwd() + os.sep + "app" + os.sep + "ablation_study" + os.sep

RESULTS_FILE = starting_path + "combined_ablation_results.jsonl"


def save_result(model_name, dataset_name, config_name, num_rows_initial_dataset, initial_dataset_error_counts,
                final_dataset_error_counts, removed_error_counts, added_error_counts, same_error_counts,
                total_removed_errors, total_added_errors, total_same_errors, total_actions_on_error_rows,
                total_final_dataset_errors, total_initial_dataset_errors, num_cols_final_dataset,
                num_cols_initial_dataset, num_initial_data_points, num_final_data_points, total_action_count,
                redundant_action_count, total_invalid_action_count, num_rows_final_dataset,
                total_partial_failure_action_count):
    result = {
        "timestamp": datetime.now().isoformat(),
        "model": model_name,
        "dataset": dataset_name,
        "ablation": config_name,
        "num_rows_initial_dataset": num_rows_initial_dataset,
        "num_rows_final_dataset": num_rows_final_dataset,
        "initial_errors": initial_dataset_error_counts,
        "final_errors": final_dataset_error_counts,
        "removed_errors": removed_error_counts,
        "added_errors": added_error_counts,
        "same_errors": same_error_counts,
        "total_removed_errors": total_removed_errors,
        "total_added_errors": total_added_errors,
        "total_same_errors": total_same_errors,
        "total_actions_on_error_rows": total_actions_on_error_rows,
        "total_final_dataset_errors": total_final_dataset_errors,
        "total_initial_dataset_errors": total_initial_dataset_errors,
        "num_cols_final_dataset": num_cols_final_dataset,
        "num_cols_initial_dataset": num_cols_initial_dataset,
        "num_initial_data_points": num_initial_data_points,
        "num_final_data_points": num_final_data_points,
        "total_action_count": total_action_count,
        "redundant_action_count": redundant_action_count,
        "total_invalid_action_count": total_invalid_action_count,
        "total_partial_failure_action_count": total_partial_failure_action_count
    }

    with open(RESULTS_FILE, "a") as f:
        f.write(json.dumps(result) + "\n")

    print("SAVED RESULTS TO", RESULTS_FILE)

action_log_path = sys.argv[1]
final_dataset_path = sys.argv[2]
initial_dataset_path = sys.argv[3]

if __name__  == "__main__":

    # Evaluating the LLM actions

    #with open(action_log_path, 'r') as f:
    #    ablation_study_results = json.load(f)

    successful_action_counts = {
        "delete_wrangle": 0,
        "impute_wrangle": 0,
        "delete_column": 0
    }

    failed_action_counts = {
        "delete_wrangle": 0,
        "impute_wrangle": 0,
        "delete_column": 0
    }

    invalid_action_counts = {}

    total_successful_action_count = 0
    total_invalid_action_count = 0
    total_partial_failure_action_count = 0
    redundant_action_count = 0

    # A list of tuples (tuples of (row, col))
    successful_row_cols_action_dict = {
        "impute_wrangle": [],
        "delete_wrangle": [],
        "delete_column": []
    }

    failed_row_cols_action_dict = {
        "impute_wrangle": [],
        "delete_wrangle": [],
        "delete_column": []
    }

    failed_action_reason_count_dict = {}

    # Used for sanity check
    expected_dataset = None
    load_dataset_count = 0
    redundant_actions_dict = {}

    all_affected_positions = set()

    with open(action_log_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for action_log_row in reader:

            action_name = action_log_row["action_name"]
            if action_name == "impute_wrangle_wrangle":
                action_name = "impute_wrangle"
            elif action_name == "delete_wrangle_wrangle":
                action_name = "delete_wrangle"
            elif action_name == "delete_column_wrangle":
                action_name = "delete_column"


            print("ACTION NAME", action_name)
            print("ACTION SUCCESS STATUS", action_log_row["action_successful"])
            action_success_status = action_log_row["action_successful"].lower()
            action_failed = None

            if action_success_status == "action_failed":
                action_failed = True
            elif action_success_status == "partial_failure":
                total_partial_failure_action_count += 1

            if action_success_status != "action_success":
                print("ACTION LOG ERROR", action_log_row["action_error_message"])


            error_message = action_log_row["action_error_message"]

            # Sanity Checks =============================
            # if total_action_count == 0:
            #     expected_dataset = action_log_row["dataset_id"]
            # else:
            #     assert not action_log_row["dataset_id"] == expected_dataset, f"Dataset ID {action_log_row['dataset_id']} does not match expected dataset ID {expected_dataset}"

            if action_name == "load_dataset":
                load_dataset_count += 1
                assert not load_dataset_count > 1, "The \'load_dataset\' action was called more than once"
            # =============================================

            # Action is not an action we're interested in keeping track of
            if action_name not in successful_action_counts.keys():
                print("ACTION NAME NOT IN SUCCESSFUL ACTION COUNT KEYS")
                continue


            action_details = json.loads(action_log_row["action_details"])

            if action_details is not None:
                rows = action_details["row_ids"]
                columns = action_details["cols"]
                affected_positions = get_all_affected_positions(rows, columns)

            if action_failed:
                #if error_message.startswith("InvalidActionError"):

                total_invalid_action_count += 1
                failed_action_counts[action_name] = failed_action_counts[action_name] + 1
                shorted_error_message = error_message[:30]

                failed_action_reason_count_dict[shorted_error_message] = failed_action_reason_count_dict.get(shorted_error_message, 0) + 1

                if action_details is not None:

                    failed_row_cols_action_dict[action_name].extend(affected_positions)



                continue

            affected_positions = get_all_affected_positions(rows, columns)
            all_affected_positions = all_affected_positions.union(set(affected_positions))
            # Check if action redundant
            redundant_positions = set(affected_positions) & set(successful_row_cols_action_dict["impute_wrangle"] + successful_row_cols_action_dict["delete_wrangle"] + successful_row_cols_action_dict["delete_column"])

            if len(redundant_positions) > 0:
                redundant_action_count += 1
                #print("ACTION NAME:", action_name)
                #print("REDUNDANT POSITIONS", redundant_positions)
                # TODO: should I keep count of anything else about redundant actions?

            # Update the counters
            total_successful_action_count += 1
            successful_action_counts[action_name] = successful_action_counts[action_name] + 1
            successful_row_cols_action_dict[action_name].extend(affected_positions)

    # Evaluating the final dataset
    # Count the number of each type of error the dataset starts with and also count how many of each type in the final dataset



    starting_path_all_starting_datasets = starting_path + os.sep + "all_starting_datasets" + os.sep



    # pass csv as df into create_error_df, count each error, take note of where each error was
    final_dataset = pd.read_csv(final_dataset_path, index_col=False)
    final_dataset = final_dataset.drop(columns=["ID"])
    if "index" in final_dataset.columns:
        final_dataset = final_dataset.drop(columns=["index"])
    initial_dataset = pd.read_csv(initial_dataset_path, index_col=False)


    # Hacky way of getting all the names (will not work if naming convention for action_log changes
    model_name = action_log_path.split("/")[-1].split("_")[2].split(".")[0]
    dataset_name = initial_dataset_path.split("/")[-1].split(".")[0]

    final_dataset_error_df = create_error_df(final_dataset)
    initial_dataset_error_df = create_error_df(initial_dataset)


    num_rows_final_dataset = len(final_dataset)
    num_rows_initial_dataset = len(initial_dataset)

    num_cols_final_dataset = len(final_dataset.columns)
    num_cols_initial_dataset = len(initial_dataset.columns)

    num_initial_data_points = num_cols_initial_dataset * num_rows_initial_dataset
    print("NUM INITIAL DATAPOINTS", num_initial_data_points)
    num_final_data_points = num_cols_final_dataset * num_rows_final_dataset
    print("NUM FINAL DATAPOINTS", num_final_data_points)

    # Compare error locations & counts with original dataset
    final_dataset_condensed_error_dict = condense_error_df(final_dataset_error_df)
    initial_dataset_condensed_error_dict = condense_error_df(initial_dataset_error_df)

    # Count errors on each
    final_dataset_error_counts = {
        "mismatch": len(final_dataset_condensed_error_dict["mismatch"]),
        "incomplete": len(final_dataset_condensed_error_dict["incomplete"]),
        "anomaly": len(final_dataset_condensed_error_dict["anomaly"]),
        "missing": len(final_dataset_condensed_error_dict["missing"]),
    }
    total_final_dataset_errors = sum(final_dataset_error_counts.values())

    initial_dataset_error_counts = {
        "mismatch": len(initial_dataset_condensed_error_dict["mismatch"]),
        "incomplete": len(initial_dataset_condensed_error_dict["incomplete"]),
        "anomaly": len(initial_dataset_condensed_error_dict["anomaly"]),
        "missing": len(initial_dataset_condensed_error_dict["missing"]),
    }

    total_initial_dataset_errors = sum(initial_dataset_error_counts.values())
    actions_on_error_rows_counts = {
        "mismatch": len(set(initial_dataset_condensed_error_dict["mismatch"]) & all_affected_positions),
        "incomplete":len(set(initial_dataset_condensed_error_dict["incomplete"]) & all_affected_positions) ,
        "anomaly": len(set(initial_dataset_condensed_error_dict["anomaly"]) & all_affected_positions) ,
        "missing": len(set(initial_dataset_condensed_error_dict["missing"]) & all_affected_positions) ,
    }

    total_actions_on_error_rows = sum(actions_on_error_rows_counts.values())

    actions_on_error_positions = []

    final_dataset_rows_with_errors_set = set()
    for key in final_dataset_condensed_error_dict:

        key_rows_with_errors = [row_val[0] for row_val in final_dataset_condensed_error_dict[key]]

        final_dataset_rows_with_errors_set.update(key_rows_with_errors)

    final_dataset_total_num_rows_with_errors = len(final_dataset_rows_with_errors_set)

    initial_dataset_rows_with_errors_set = set()

    for key in initial_dataset_condensed_error_dict:
        key_rows_with_errors = [row_val[0] for row_val in initial_dataset_condensed_error_dict[key]]

        initial_dataset_rows_with_errors_set.update(key_rows_with_errors)

    initial_dataset_total_num_rows_with_errors = len(initial_dataset_rows_with_errors_set)

    # Check how these two dicts overlap
    removed_error_counts = {
        "mismatch": len(set(initial_dataset_condensed_error_dict["mismatch"]) - set(final_dataset_condensed_error_dict["mismatch"])),
        "incomplete": len(set(initial_dataset_condensed_error_dict["incomplete"]) - set(final_dataset_condensed_error_dict["incomplete"])),
        "anomaly": len(set(initial_dataset_condensed_error_dict["anomaly"]) - set(final_dataset_condensed_error_dict["anomaly"])),
        "missing": len(set(initial_dataset_condensed_error_dict["missing"]) - set(final_dataset_condensed_error_dict["missing"])),
    }

    added_error_counts = {
        "mismatch": len(set(final_dataset_condensed_error_dict["mismatch"]) - set(initial_dataset_condensed_error_dict["mismatch"])),
        "incomplete": len(set(final_dataset_condensed_error_dict["incomplete"]) - set(initial_dataset_condensed_error_dict["incomplete"])),
        "anomaly": len(set(final_dataset_condensed_error_dict["anomaly"]) - set(initial_dataset_condensed_error_dict["anomaly"])),
        "missing": len(set(final_dataset_condensed_error_dict["missing"]) - set(initial_dataset_condensed_error_dict["missing"])),
    }

    initial_error_locations = set()
    final_error_locations = set()

    # Add every (row, column) error from the initial dictionary
    for error_type, positions in initial_dataset_condensed_error_dict.items():
        for position in positions:
            initial_error_locations.add(tuple(position))

    # Add every (row, column) error from the final dictionary
    for error_type, positions in final_dataset_condensed_error_dict.items():
        for position in positions:
            final_error_locations.add(tuple(position))

    introduced_errors = final_error_locations - initial_error_locations

    total_added_errors = len(introduced_errors)

    same_error_counts = {
        "mismatch": len(set(final_dataset_condensed_error_dict["mismatch"]) & set(initial_dataset_condensed_error_dict["mismatch"])),
        "incomplete": len(set(final_dataset_condensed_error_dict["incomplete"]) & set(initial_dataset_condensed_error_dict["incomplete"])),
        "anomaly": len(set(final_dataset_condensed_error_dict["anomaly"]) & set(initial_dataset_condensed_error_dict["anomaly"])),
        "missing": len(set(final_dataset_condensed_error_dict["missing"]) & set(initial_dataset_condensed_error_dict["missing"])),
    }


    total_removed_errors = sum(removed_error_counts.values())
    #total_added_errors = sum(added_error_counts.values())
    total_same_errors = sum(same_error_counts.values())

    #print("INITIAL:", initial_dataset_condensed_error_dict)
    #print("FINAL:", final_dataset_condensed_error_dict)

    print("REMOVED:", removed_error_counts)
    #print("ADDED:", added_error_counts)
    print("SAME:", same_error_counts)

    print("TOTAL REMOVED:", total_removed_errors)
    print("TOTAL ADDED:", total_added_errors)
    print("TOTAL SAME:", total_same_errors)

    # print results
    print("------------------------------ RESULTS ------------------------------")

    starting_path = os.getcwd() + os.sep + "app" + os.sep + "ablation_study" + os.sep
    all_results_json_path = starting_path + os.sep + "all_results.json"

    total_action_count = total_successful_action_count + total_invalid_action_count

    print("total_successful_action_count: ", total_successful_action_count)
    print("total_invalid_action_count: ", total_invalid_action_count)

    print("redundant_action_count: ", redundant_action_count)
    print("failed_action_counts", failed_action_counts)
    print("failed_action_reason_count_dict", failed_action_reason_count_dict)
    print("successful_action_counts", successful_action_counts)
    print("total_actions_on_error_rows", total_actions_on_error_rows)

    print("num_rows_final_dataset", num_rows_final_dataset)
    print("num_rows_initial_dataset", num_rows_initial_dataset)

    print("final_dataset_error_counts", final_dataset_error_counts)
    print("initial_dataset_error_counts", initial_dataset_error_counts)
    print("removed_errors", removed_error_counts)
    #
    # if os.path.exists(all_results_json_path):
    #     with open(all_results_json_path, "r") as all_results_file:
    #         all_results_dict = json.load(all_results_file)
    # else:
    #     all_results_dict = {"removed_error_counts": {
    #                     "baseline":
    #                         {"dirty_global_air_pollution_dataset": None,
    #                          "dirty_winequality-red": None,
    #                          "disability_compensation": None,
    #                             "leading_causes_death": None
    #                         },
    #         "remove_error_log":
    #             {"dirty_global_air_pollution_dataset": None,
    #              "dirty_winequality-red": None,
    #              "disability_compensation": None,
    #              "leading_causes_death": None
    #              },
    #         "remove_data_profile":
    #                         {"dirty_global_air_pollution_dataset": None,
    #                          "dirty_winequality-red": None,
    #                          "disability_compensation": None,
    #                             "leading_causes_death": None
    #                         },
    #         "remove_action_log":
    #                         {"dirty_global_air_pollution_dataset": None,
    #                          "dirty_winequality-red": None,
    #                          "disability_compensation": None,
    #                             "leading_causes_death": None
    #                         },
    #         "remove_full_dataset":
    #                         {"dirty_global_air_pollution_dataset": None,
    #                          "dirty_winequality-red": None,
    #                          "disability_compensation": None,
    #                             "leading_causes_death": None
    #                         },
    #         "remove_action_log_limit":
    #             {"dirty_global_air_pollution_dataset": None,
    #              "dirty_winequality-red": None,
    #              "disability_compensation": None,
    #              "leading_causes_death": None
    #              },
    #
    #     }
    #                     }
    # #
    #
    # dataset_name = initial_dataset_path.split("/")[-1].split(".")[0]
    # all_results_dict["removed_error_counts"][config_name][dataset_name] = removed_error_counts

    print("added_errors", added_error_counts)
    print("same_errors", same_error_counts)



    config_names = [
        "baseline",
        "no_error_log",
        "no_data_profile",
        "no_full_dataset",
        "no_action_log_limit",
        "no_action_log"
    ]
    from pathlib import Path

    filename = Path(action_log_path).name

    config_name = None
    for config in config_names:
        if config in filename:
            config_name = config
            print("FILENAME: ", filename)
            print("FILENAME.TYPe: ", type(filename))
            print("ACTION_LOG_PATH: ", action_log_path)
            print("CONFIG MATCH: ", config_name)
            break

    print(dataset_name)

    save_result(model_name=model_name, dataset_name=dataset_name, config_name=config_name,
                num_rows_initial_dataset=num_rows_initial_dataset,
                initial_dataset_error_counts=initial_dataset_error_counts,
                final_dataset_error_counts=final_dataset_error_counts, removed_error_counts=removed_error_counts,
                added_error_counts=added_error_counts, same_error_counts=same_error_counts,
                total_removed_errors=total_removed_errors, total_added_errors=total_added_errors,
                total_same_errors=total_same_errors, total_actions_on_error_rows=total_actions_on_error_rows,
                total_final_dataset_errors=total_final_dataset_errors,
                total_initial_dataset_errors=total_initial_dataset_errors,
                num_cols_final_dataset=num_cols_final_dataset, num_cols_initial_dataset=num_cols_initial_dataset,
                num_initial_data_points=num_initial_data_points, num_final_data_points=num_final_data_points,
                total_action_count=total_action_count, redundant_action_count=redundant_action_count,
                total_invalid_action_count=total_invalid_action_count, num_rows_final_dataset=num_rows_final_dataset,
                total_partial_failure_action_count=total_partial_failure_action_count)








