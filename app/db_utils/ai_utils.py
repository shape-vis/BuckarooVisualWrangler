import os
from app.db_utils.execute_sql import copy_table_to_csv
from app import logger
import json
import ast

import random
import time


# Overwriting the csv every time the LLM needs it to be updated; we don't really need to save the old ones

def update_csvs_for_llm(error_table_name, data_profile_name, action_log_name, full_dataset_name):
    print(f"UPDATE CSVS FOR LLM PATHS error_table_name: {error_table_name}, data_profile_name: {data_profile_name} action_log_name: {action_log_name}")

    action_log_csv_path = "action_log.csv"
    error_log_csv_path = "error_log.csv"
    data_profile_csv_path = "data_profile.csv"
    full_dataset_csv_path = "full_dataset.csv"

    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    FILES_FOR_LLM_PATH = os.path.abspath(os.path.join(_THIS_DIR, '..', 'files_for_llm'))

    action_log_csv_path = FILES_FOR_LLM_PATH + '/' + f'{action_log_csv_path}'
    error_log_csv_path = FILES_FOR_LLM_PATH + '/' + f'{error_log_csv_path}'
    data_profile_csv_path = FILES_FOR_LLM_PATH + '/' + f'{data_profile_csv_path}'
    full_dataset_csv_path = FILES_FOR_LLM_PATH + '/' + f'{full_dataset_csv_path}'


    table_name_tuple_list =  [(action_log_name, action_log_csv_path),
                              (error_table_name, error_log_csv_path),
                              (data_profile_name, data_profile_csv_path),
                              (full_dataset_name, full_dataset_csv_path)]

    write_tables_to_csv(table_name_tuple_list)

    return (error_log_csv_path, data_profile_csv_path, action_log_csv_path, full_dataset_csv_path)



def write_tables_to_csv(table_name_tuple_list):
    from app import engine
    for (table_name, csv_path) in table_name_tuple_list:

        # Clear the existing CSV file if it exists
        if os.path.exists(csv_path):
            os.remove(csv_path)

        copy_table_to_csv(table_name, csv_path, engine)


def parse_json_response(llm_json_response):
    try:
        return json.loads(llm_json_response)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(llm_json_response)
        except (ValueError, SyntaxError) as e:
            logger.exception(f"Could not parse response as dict or JSON")


def call_with_retry(function, func_args, max_tries=5):
    for attempt in range(max_tries):
        try:
            result = function(*func_args)

            return result
        except Exception:
            logger.exception("Error occurred while calling LLM function")
            if attempt == max_tries - 1:
                raise

            # TODO: is this okay
            delay = 10
            delay *= random.uniform(0.5, 1.5)  # jitter
            time.sleep(delay)



def get_api_key(provider):
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY"
    }

    key = os.environ.get(key_map[provider])
    if key is None:
        raise ValueError(f"Could not find API key for {provider}")
    return key







