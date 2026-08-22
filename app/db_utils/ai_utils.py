import os
from app.db_utils.execute_sql import copy_table_to_csv
from app import logger
import json
import ast

import random
import time


# Overwriting the csv every time the LLM needs it to be updated; we don't really need to save the old ones

def update_csvs_for_llm(error_table_name, data_profile_name, action_log_name, full_dataset_name,
                        dataset_sample_percent):
    """
    Updates the csv files for the LLM to access the error log, data profile, action log, and full dataset tables.
    :param error_table_name: the name of the error table
    :param data_profile_name: the name of the profile table
    :param action_log_name: the name of the action log table
    :param full_dataset_name: the name of the full dataset table
    :return: Tuple of csv paths (error log, data profile, action log, full dataset table)
    """
    action_log_csv_path = "action_log.csv"
    error_log_csv_path = "error_log.csv"
    data_profile_csv_path = "data_profile.csv"
    sampled_dataset_csv_path = "sampled_dataset.csv"

    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    FILES_FOR_LLM_PATH = os.path.abspath(os.path.join(_THIS_DIR, '..', 'files_for_llm'))

    action_log_csv_path = FILES_FOR_LLM_PATH + '/' + f'{action_log_csv_path}'
    error_log_csv_path = FILES_FOR_LLM_PATH + '/' + f'{error_log_csv_path}'
    data_profile_csv_path = FILES_FOR_LLM_PATH + '/' + f'{data_profile_csv_path}'
    sampled_dataset_csv_path = FILES_FOR_LLM_PATH + '/' + f'{sampled_dataset_csv_path}'

    table_name_tuple_list =  [(action_log_name, action_log_csv_path),
                              (error_table_name, error_log_csv_path),
                              (data_profile_name, data_profile_csv_path)]

    write_tables_to_csv(table_name_tuple_list)

    # diff function for sample table because the sampled dataset isn't an existing table
    create_sample_table_csv(full_dataset_name, dataset_sample_percent, sampled_dataset_csv_path)

    return (error_log_csv_path, data_profile_csv_path, action_log_csv_path, sampled_dataset_csv_path)



def write_tables_to_csv(table_name_tuple_list):
    """
    Writes tables to a csv file (so that the LLM can access them) and overwrites the csv file if it already exists
    :param table_name_tuple_list: a list of tuples of the form (action_log_name, action_log_csv_path),
    :return: None
    """
    from app import engine
    for (table_name, csv_path) in table_name_tuple_list:

        # Clear the existing CSV file if it exists
        if os.path.exists(csv_path):
            os.remove(csv_path)

        copy_table_to_csv(table_name, csv_path, engine)


def parse_json_response(llm_json_response):
    """
    Tries to parse json response from llm
    """
    try:
        return json.loads(llm_json_response)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(llm_json_response)
        except (ValueError, SyntaxError) as e:
            logger.exception(f"Could not parse response as dict or JSON")
            raise


def call_with_retry(function, func_args, requests_per_minute_limit, max_tries=5):
    """
    Retry function call until max tries is reached or the function call succeeds.
    :param function: the function to call
    :param func_args: the function arguments
    :param max_tries: the maximum number of retries
    :return: the result of the function call
    """

    from app.routes.ai_routes import call_rate_limited_api
    for attempt in range(max_tries):
        try:

            result = call_rate_limited_api(function,func_args, requests_per_minute_limit)

            return result
        except Exception:
            logger.exception(f"Error occurred while calling call_with_retry. Num retries: {attempt}")
            if attempt == max_tries - 1:
                raise

            # TODO: make sure this is enough delay
            delay = 10
            delay *= random.uniform(0.5, 1.5)  # jitter
            time.sleep(delay)



def get_api_key(provider):
    """
    Retrieves the API key for the specified provider.
    :param provider: The provider for which to retrieve the API key
    :return: The API key for the specified provider
    """
    key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY"
    }

    key = os.environ.get(key_map[provider])
    if key is None:
        raise ValueError(f"Could not find API key for {provider}")
    return key

def create_sample_table_csv(table_name, dataset_sample_percent, csv_path):
    from app.db_utils.execute_sql import execute_sql
    from app import engine
    try:

        if dataset_sample_percent == 100.0:
            query = (f'''
                    COPY (
                        SELECT *
                        FROM "{table_name}"
                        ORDER BY RANDOM()
                        )
                    TO '{csv_path}'
                    WITH CSV HEADER
                    ''')
        else:
            query = (f'''
                    COPY (
                        SELECT *
                        FROM "{table_name}"
                        ORDER BY RANDOM()
                        LIMIT FLOOR(
                            (
                            SELECT COUNT(*) * {dataset_sample_percent} 
                            FROM "{table_name}"
                            )
                        )
                    )
                    TO '{csv_path}'
                    WITH CSV HEADER
                    ''')



        execute_sql(query, engine)
    except Exception as e:
        logger.exception(f"Error: Could not sample table {table_name}")
        raise e











