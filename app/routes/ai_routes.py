
from litellm import completion, get_max_tokens, token_counter
from app import app, engine, logger
from app.db_utils.ai_utils import update_csvs_for_llm, get_api_key, parse_json_response
from app.db_utils.execute_sql import fetch_sql, execute_sql

from app.db_utils.ai_utils import call_with_retry
from flask import request
from pyrate_limiter import Duration, Rate, Limiter

from app.server_utils.logger_utils import update_action_log

from datetime import datetime, timezone
from app.server_utils.logger_utils import InvalidActionError


AI_SETTINGS_TABLE_NAME = "ai_settings"

ablations = ["include_data_profile", "include_dataset_context", "include_action_plan", "include_action_plan_translation"]
valid_actions = ["delete_wrangle", "impute_wrangle", "delete_column", "plan_end"]

'''
    LLM Query plans: 
    - just the action plan in json
    - action plan in text -> translate to json
    - 
'''

def query_llm_for_text_action_plan(model, provider, api_key, error_log_csv_path, action_log_csv_path,
                                   data_profile_csv_path, full_dataset_csv_path):
    """
    Queries LLM to generate a text action plan after given context
    :param model: name of the model
    :param provider: name of the model provider
    :param api_key: API key
    :param error_log_csv_path: path to the error log
    :param action_log_csv_path: path to the action log
    :param data_profile_csv_path: path to the data profile
    :param full_dataset_csv_path: path to the full dataset csv
    """
    action_limit = 5
    system_prompt = (f"You are data scientist. Create an action plan of the top {action_limit} steps the user could do that efficiently cleans this dataset while"
                     f"also personalizing the actions to better suit the users wants based on the action log.")

    csv_text = {}

    with open(action_log_csv_path, "r") as f:
        csv_text[action_log_csv_path] = f.read()

    with open(data_profile_csv_path, "r") as f:
        csv_text[data_profile_csv_path] = f.read()

    with open(error_log_csv_path, "r") as f:
        csv_text[error_log_csv_path] = f.read()

    with open(full_dataset_csv_path, "r") as f:
        csv_text[full_dataset_csv_path] = f.read()

    llm_text_plan_rules = '''
        Each step of the action plan should be numbered and begin with the selection of columns and rows.
        The columns should the string names columns, or None depending on the action you take. You may only perform an action on TWO COLUMNS AT A TIME. There should only be at most two columns selected
        while the rows should be each individual rows to perform the wrangles on.
        At each step, determine a SINGULAR wrangling
        action to perform on the selected data. 
        You must specify which datapoints to perform each action on, specified with rows and column.
            - row: a list of the rows to apply action to. Refer to the "ID" column to decide which row to delete.
            - column: the name of a single column to apply action to
        
        Here are the wrangles that you can perform on the data:
            - Delete: Deletes the selection of rows; the value for columns is ignored as the row for all columns will be deleted. Rows should be specified and columns should be an empty list.
            - Impute: Imputes the selection of data with either the mean if numeric or the mode if categorical. The rows and columns should be specified. If you only have one column to impute, only specify one column.
            - Delete column: Deletes an entire column of the dataset. The columns should be specified and rows should be empty (empty list). YOU MAY NOT DELETE THE ID COLUMN
            
            - Stop: stop wrangling the data if the data is at a satisfactory state. The action plan does not have to
                end with a stop action as the dataset will be reevaluated again later to see if there are any more actions that need to be done.
                The stop action should only be used if there are no more actions needed to be done. 
                
        OTHER RULES THAT YOU MUST FOLLOW
        - YOU MAY NOT DELETE THE "ID" COLUMN
        - DO NOT CREATE NEW ACTIONS
        - ONLY OUTPUT THE ACTION PLAN, NOTHING ELSE
    '''

    additional_details = f''' Here are the contents of each of the CSVs that you can use to inform the actions in your action plan:
    action_log: {csv_text[action_log_csv_path]}\n
    data_profile: {csv_text[data_profile_csv_path]}\n
    error_log: {csv_text[error_log_csv_path]}\n
    full_dataset: {csv_text[full_dataset_csv_path]}\n
    '''
    print("FULL_DATASET_CSV_PATH", full_dataset_csv_path)

    full_message = llm_text_plan_rules + additional_details
    print("FULL MESSAGE TO LLM:", full_message)
    #print("full_message", full_message)
    #print("len(full_message)", len(full_message))
    #print("estimated num tokens", len(full_message) / 4)
    full_model_name = provider + '/' + model
    print("MAX TOKENS", get_max_tokens(full_model_name))
    print("TOKEN COUNT", token_counter(model=full_model_name, text=full_message))

    response = completion(
        model=full_model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_message},
        ],
        api_key=api_key
    )

    llm_text_response = response.choices[0].message.content
    print("LLM TEXT RESPONSE", llm_text_response)

    return llm_text_response


def query_llm_for_action_plan_translation(model, provider, api_key, text_action_plan):
    """
    Queries LLM to translate from a text plan to JSON
    :param model: name of the model
    :param provider: name of the model provider
    :param api_key: API key
    :param text_action_plan: Plan to be translated to JSON
    :return: JSON of the action plan
    """
    system_prompt = "You are a translator that translates actions from natural language text to JSON where each row is an action.  Translate this action plan from text to JSON."

    llm_translated_plan_rules = '''
        Each step of the action plan should be a dict with the following keys: "action_name", "rows_to_wrangle", "columns".
        Here are the valid actions and their names: 
        - Delete -> "delete_wrangle"
        - Impute -> "impute_wrangle"
        - Delete column -> "delete_column"
        - Stop -> "plan_end"
        
        The value of "rows_to_wrangle" is list of rows to wrangle.
        The value of "columns" is a list of the string name(s) of AT MOST TWO columns to wrangle. If no columns are provided, it should be translated into an empty list.

        OTHER RULES THAT YOU MUST FOLLOW
        - DO NOT CREATE NEW ACTIONS
        - THE RESULT MUST BE IN JSON FORMAT
    '''

    text_action_plan_prompt = f'''
    Here is the text action plan you must translate to JSON:
    {text_action_plan}
    '''

    response = completion(
        model=provider + '/' + model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": llm_translated_plan_rules + text_action_plan_prompt},
        ],
        api_key=api_key
    )

    llm_text_response = response.choices[0].message.content
    print("LLM TEXT TRANSLATION RESPONSE", llm_text_response)

    json_action_plan = parse_json_response(llm_text_response)

    return json_action_plan


# This actually isn't being used yet but will hopefully be used in the future
def query_llm_for_dataset_context(model, api_key, column_names, user_provided_dataset_context, dataset_name):
    """
    Queries LLM to generate context about the dataset (dataset description, column descriptions)
    :param model: name of the model
    :param api_key: API key
    :param column_names: list of column names
    :param user_provided_dataset_context: context provided by the user
    :param dataset_name: name of the dataset
    :return: JSON of the dataset context
    """
    system_prompt = ("You are a data scientist that is given a dataset. "
                     "You are to provide context about the dataset. You are to give a description of the dataset as well"
                     "as a brief description of each column. If you do not know what a column is, you can have the"
                     "description be 'N/A'")

    llm_dataset_context_rules = f'''
        The dataset is named: {dataset_name}
        The columns in the dataset are: {column_names}
        The user has provided the following context about the dataset: {user_provided_dataset_context}
        
        Using this information, create a JSON object with the following keys: 'dataset_description', 'column_descriptions'.
        The value of 'dataset_description' is the description of the dataset.
        The value of 'column_descriptions' is a dictionary where the keys are the column names and the values are the descriptions of each column.
        If you do not know what a column is, you can have the description be None.
    '''

    response = completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": llm_dataset_context_rules},
        ],
        api_key=api_key
    )

    llm_text_response = response.choices[0].message.content
    return llm_text_response

def get_settings_dict(engine):
    """
    Retrieves the model name and provider from the settings table.
    :return: Dictionary containing model name and provider, or None if not found
    """
    try:
        result = fetch_sql(f"SELECT model_name, provider, requests_per_minute_limit, dataset_sample_percent FROM {AI_SETTINGS_TABLE_NAME} WHERE id = :id", False, engine, {"id": 1})
        row = result[0]

        if result is not None:
            model_name = row.model_name  # or row[0]
            provider = row.provider
            requests_per_minute_limit = row.requests_per_minute_limit
            print("MODEL NAME", model_name, "PROVIDER", provider)
            settings_dict = {"model_name": model_name, "provider": provider, "requests_per_minute_limit": requests_per_minute_limit, "dataset_sample_percent": row.dataset_sample_percent}
        else:
            settings_dict = None

        return settings_dict
    except Exception as e:
        logger.exception("Error retrieving settings from table.")
        raise

def call_rate_limited_api(api_request_function, request_function_args, requests_per_minute_limit):
    limiter = get_or_create_limiter(requests_per_minute_limit)

    # TODO: when updating to have multiple users, have to change this to be the user id
    limiter.try_acquire("user")

    return api_request_function(*request_function_args)

def get_or_create_limiter(requests_per_minute_limit):
    """
    Depending on API, allows user to modify rate limit
    """
    from app import db_operations

    if requests_per_minute_limit is not None and requests_per_minute_limit != db_operations.reqs_per_minute_limit:
        limiter = Limiter(Rate(requests_per_minute_limit, Duration.MINUTE))
        db_operations.reqs_per_minute_limiter = limiter
        db_operations.reqs_per_minute_limit = requests_per_minute_limit
    else:
        limiter = db_operations.reqs_per_minute_limiter

    return limiter

# TODO: clean up code
@app.post('/api/ai_helper/perform_llm_action')
def perform_llm_action():
    """
    Perform action using action json from LLM
    :param action_dict: Dictionary containing action details
    :return: JSON response indicating success or failure
    """
    from app import db_operations
    from app.db_utils.query import remove_rows_by_ids, impute_by_ids, delete_column
    from app.routes.wrangler_routes_sql import update_errors_table, update_data_profile_table
    timestamp = datetime.now(timezone.utc)

    try:
        action_dict = request.get_json()
        main_table_name = db_operations.main_table_name
        action_name = str(action_dict["action_name"])


        rows_to_wrangle = action_dict["rows_to_wrangle"]
        if rows_to_wrangle is not None:
            rows_to_wrangle = list(rows_to_wrangle)

        columns = action_dict["columns"]
        if columns is not None:
            columns = list(columns)


        action_details = {"row_ids": rows_to_wrangle, "cols": columns}

        if action_name == "plan_end":
            return {
                "success": True
            }

        # Apply the changes directly to the table (no preview)
        #if action_name == "delete" and rows_to_wrangle == "ALL":
        #    # The LLM is trying to say that it wants to delete this entire column
        #contine
        print("MAIN TABLE NUMERIC COLS", db_operations.col_types.numeric_cols)
        print("MAIN TABLE CATEGORICAL COLS", db_operations.col_types.categorical_cols)

        all_cols = list(db_operations.col_types.numeric_cols) + list(db_operations.col_types.categorical_cols)

        # Validate/filter rows and columns BEFORE modifying the database

        if action_name == "delete_wrangle":
            # rows are required
            if rows_to_wrangle is None:
                raise InvalidActionError(
                    "InvalidActionError: rows_to_wrangle should not be None for delete_wrangle"
                )

            existing_ids = {
                row[0]
                for row in fetch_sql(
                    f'SELECT "ID" FROM "{main_table_name}"',
                    False,
                    engine
                )
            }
            valid_rows = []
            invalid_rows = []

            for r in rows_to_wrangle:
                try:
                    r_int = int(r)
                    if r_int in existing_ids:
                        valid_rows.append(r_int)
                    else:
                        invalid_rows.append(r)
                except (ValueError, TypeError):
                    invalid_rows.append(r)


            partial_failure = len(invalid_rows) > 0
            action_details["invalid_rows"] = invalid_rows

            if not valid_rows:
                raise InvalidActionError(
                    "InvalidActionError: None of the specified row IDs exist"
                )

            # Only execute valid rows
            remove_rows_by_ids(table=main_table_name, ids=valid_rows)


        elif action_name == "delete_column":
            # columns are required
            if columns is None:
                raise InvalidActionError(
                    "InvalidActionError: columns should not be None for delete_column"
                )

            valid_cols = [
                col for col in columns
                if col in all_cols and col != "ID"
            ]
            invalid_cols = [c for c in columns if c not in all_cols or c == "ID"]

            action_details["invalid_cols"] = invalid_cols
            partial_failure = len(invalid_cols) > 0

            if not valid_cols:
                raise InvalidActionError(
                    "InvalidActionError: None of the specified columns are valid"
                )

            # Only execute valid columns
            for col in valid_cols:
                delete_column(table=main_table_name, column=col)


        elif action_name == "impute_wrangle":
            # BOTH rows and columns are required
            if rows_to_wrangle is None:
                raise InvalidActionError(
                    "InvalidActionError: rows_to_wrangle should not be None for impute_wrangle"
                )

            if columns is None:
                raise InvalidActionError(
                    "InvalidActionError: columns should not be None for impute_wrangle"
                )

            existing_ids = {
                row[0]
                for row in fetch_sql(
                    f'SELECT "ID" FROM "{main_table_name}"',
                    False,
                    engine
                )
            }
            valid_rows = []
            invalid_rows = []

            for r in rows_to_wrangle:
                try:
                    r_int = int(r)
                    if r_int in existing_ids:
                        valid_rows.append(r_int)
                    else:
                        invalid_rows.append(r)
                except (ValueError, TypeError):
                    invalid_rows.append(r)

            action_details["invalid_rows"] = invalid_rows

            valid_cols = [c for c in columns if c in all_cols and c != "ID"]
            invalid_cols = [c for c in columns if c not in all_cols or c == "ID"]
            action_details["invalid_cols"] = invalid_cols

            # Some requested rows/columns were invalid
            partial_failure = (
                    len(invalid_rows) > 0 or
                    len(invalid_cols) > 0
            )

            if not valid_rows:
                raise InvalidActionError(
                    "InvalidActionError: None of the specified row IDs exist"
                )

            if not valid_cols:
                raise InvalidActionError(
                    "InvalidActionError: None of the specified columns are valid"
                )

            # Only execute valid rows/columns
            for col in valid_cols:
                impute_by_ids(
                    table=main_table_name,
                    col=col,
                    ids=valid_rows
                )

        action_duration = (datetime.now(timezone.utc) - timestamp).total_seconds()

        if partial_failure:
            action_success_status = "partial_failure"
        else:
            action_success_status = "action_success"


        if columns is not None and len(columns) > 1:
            update_errors_table(main_table_name, columns)
            update_data_profile_table(main_table_name, columns)
        else:
            update_errors_table(main_table_name)
            update_data_profile_table(main_table_name)

        # Gets action details dict a different way from execute_wrangle because execute
        if not action_name == "plan_end":
            update_action_log(main_table_name=main_table_name, action_name=action_name, action_details=action_details,
                              engine=engine, timestamp=timestamp, action_success_status=action_success_status, llm_suggested=True,
                              action_duration=action_duration)
            print("PERFORM LLM ACTION SUCCESSFULLY UPDATED ACTION LOG")
        return {
            "success": True
        }
    except InvalidActionError as e:
        logger.exception("Failed performing llm action because of invalid action")

        # with the assumption that action_name is not None
        if action_name is not None and not action_name == "plan_end":
            update_action_log(main_table_name=main_table_name, action_name=action_name, action_details=action_details,
                              engine=engine, timestamp=timestamp, action_success_status="action_fail", llm_suggested=True,
                              action_error_message=str(e), reset_log=True)

        return {
            "success": False
        }
    except Exception as e:
        logger.exception("Error performing LLM action")

        # with the assumption that action_name is not None
        if action_name is not None and not action_name == "stop":
            update_action_log(main_table_name=main_table_name, action_name=action_name, action_details=action_details,
                              engine=engine, timestamp=timestamp, action_success_status="action_fail", llm_suggested=True,
                              action_error_message=str(e), reset_log=True)

        return {
            "success": False
        }

@app.post('/api/ai_helper/get_action_plan')
def get_llm_json_action_plan():
    """
    Combines LLM text action plan with translation to generate JSON action plan
    :return: Dict indicating success or failure and the json action plan
    """
    from app import db_operations, engine
    from app.server_utils.logger_utils import ACTION_LOG_TABLE_NAME
    try:

        error_table_name = db_operations.error_table_name
        data_profile_name = db_operations.dp_table_name
        full_dataset_name = db_operations.main_table_name
        action_log_name = ACTION_LOG_TABLE_NAME
        settings_dict = get_settings_dict(engine)
        model_name = settings_dict.get("model_name")
        provider = settings_dict.get("provider")
        action_log_limit = settings_dict.get("action_log_limit")
        requests_per_minute_limit = settings_dict.get("requests_per_minute_limit")
        dataset_sample_percent = settings_dict.get("dataset_sample_percent")
        api_key = get_api_key(provider)

        assert model_name is not None

        (error_log_csv_path, data_profile_csv_path, action_log_csv_path, full_dataset_csv_path) = update_csvs_for_llm(
            error_table_name, data_profile_name, action_log_name, full_dataset_name, dataset_sample_percent,
            action_log_limit)


        text_plan_func_args = (model_name, provider, api_key, error_log_csv_path,
            action_log_csv_path, data_profile_csv_path, full_dataset_csv_path)
        text_action_plan = call_with_retry(query_llm_for_text_action_plan, text_plan_func_args,
                                           requests_per_minute_limit, max_tries=15)

        translation_func_args = (model_name, provider, api_key, text_action_plan)

        json_action_plan = call_with_retry(query_llm_for_action_plan_translation, translation_func_args,
                                           requests_per_minute_limit, max_tries=15)

        return {"success": True, "json_action_plan": json_action_plan}
    except Exception as e:
        json_action_plan = None
        logger.exception("Error translating llm action plan to json")
        return {"success": False, "json_action_plan": json_action_plan}


@app.post('/api/ai_helper/update_settings_table')
def update_settings_table():
    """
    Updates the settings table which contains the model the user chose and the model provider
    :param model_name: Name of the model
    :param provider: Provider of the model
    """
    data = request.get_json()
    model_name = data.get("model_name")
    provider = data.get("provider")
    requests_per_minute_limit = data.get("requests_per_minute_limit")
    dataset_sample_percent = data.get("dataset_sample_percent")

    try:
        execute_sql(f"""
                         CREATE TABLE IF NOT EXISTS {AI_SETTINGS_TABLE_NAME}
                         (
                             id
                             INTEGER
                             PRIMARY
                             KEY,
                             model_name
                             TEXT
                             NOT
                             NULL,
                             provider
                             TEXT
                             NOT
                             NULL, 
                             requests_per_minute_limit
                             INTEGER
                             NOT
                             NULL,
                             dataset_sample_percent
                             FLOAT
                             NOT
                             NULL
                         )
                         """, engine)

        result = fetch_sql(f"SELECT id FROM {AI_SETTINGS_TABLE_NAME} WHERE id = :id", True,
            engine, {"id": 1}
        )

        if result is None:
            print("VALUE DOESN'T EXIST. INSERTING ONE")
            execute_sql(
                f"INSERT INTO {AI_SETTINGS_TABLE_NAME} (id, model_name, provider, requests_per_minute_limit, dataset_sample_percent) VALUES (:id, :model_name, :provider, :requests_per_minute_limit, :dataset_sample_percent)",
                engine, {"id": 1, "model_name": model_name, "provider": provider, "requests_per_minute_limit": requests_per_minute_limit, "dataset_sample_percent": dataset_sample_percent}
            )
        else:
            print("VALUE EXISTS, REPLACING")
            execute_sql(
                f"UPDATE {AI_SETTINGS_TABLE_NAME} SET model_name = :model_name, provider = :provider, requests_per_minute_limit = :requests_per_minute_limit, dataset_sample_percent = :dataset_sample_percent WHERE id = :id",
                engine, {"id": 1, "model_name": model_name, "provider": provider, "requests_per_minute_limit": requests_per_minute_limit, "dataset_sample_percent": dataset_sample_percent}
            )

        return {"success": True}
    except Exception as e:
        logger.exception("Error updating settings table.")

        return {"success": False}




