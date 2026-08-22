import os

from dotenv import load_dotenv
import datetime


from app import app as app_module
from app import db_operations, engine

import json

from app.db_utils.execute_sql import execute_sql
from app.routes.wrangler_routes_sql import update_data_profile_table

starting_path = os.getcwd() + os.sep + "app" + os.sep + "ablation_study" + os.sep


datasets_paths = {"dirty_winequality-red": starting_path + 'artificially_dirty_datasets' + os.sep + 'dirty_winequality-red.csv'}

# This additional col info code hasn't been merged into main, so until that happens, just using this hacky way to get more accurate LLM results
dataset_additional_info = {
    "dirty_winequality-red": {
        "text_cols": [],
        "identifier_cols": []
    },
    "": {
        "text_cols": [],
        "identifier_cols": []
    },
}

#models = [{"model": "qwen/qwen3.6-27b", "provider": "groq"}]

# Gemini 3.6 Flash
models = [{"model": "gemini-3.1-flash-lite", "provider": "gemini", "requests_per_minute_limit": 15, "dataset_sample_percent": 100.0}]

def variant(name, **overrides):
    baseline = {
        "name": "baseline",
        "include_error_log": True,
        "include_data_profile": True,

        "include_action_log": True,
        "action_log_limit": 10,
        "include_full_dataset": True
    }

    # gets the baseline and overrides the key(s) in the overrides variable
    config = {**baseline, **overrides}
    config["name"] = name
    return config


def is_stop_action(action_name):
    if action_name == "stop":
        return True
    else:
        return False


# This is a really jank way of dealing with this problem but this is the fastest way to implement this without changing too
# much of the code
def remove_errors_from_error_table(error_table_name, main_table_name, text_cols, identifier_cols):
    print("FUNC ERROR TABLE NAME:", error_table_name)
    print("FUNC DP TABLE NAME:", main_table_name)
    try:
        if not len(text_cols) == 0:
            drop_identifier_columns = ", ".join(
                f'DROP COLUMN IF EXISTS "{col}"'
                for col in text_cols
            )
            query = f"""
                    ALTER TABLE IF EXISTS "{error_table_name}"
                    {drop_identifier_columns}
                    """
            execute_sql(query, engine)

        if not len(identifier_cols) == 0:
            drop_identifier_columns = ", ".join(
                f'DROP COLUMN IF EXISTS "{col}"'
                for col in identifier_cols
            )
            query = f"""
                    ALTER TABLE IF EXISTS "{error_table_name}"
                    {drop_identifier_columns}
                    """
            execute_sql(query, engine)

        # This is really cursed I'm sorry
        # update the data profile??? Idk
        all_target_col_names = text_cols + identifier_cols
        update_data_profile_table(main_table_name, all_target_col_names)
        print("Successfully removed text / identifier columns from error and data profile tables")

    except Exception:
        logger.exception("Removing text / identifier columns from error and data profile tables failed")
        raise





if __name__ == "__main__":
    load_dotenv()

    ablation_configs = [
        variant("baseline"),
        variant("no_error_log", include_error_log=False),
        variant("no_data_profile", include_data_profile=False),
        variant("no_action_log", include_action_log=False),
        variant("no_full_dataset", include_full_dataset=False),
        variant("no_action_log_limit", action_log_limit=None) # Includes full action log
    ]

    client = app_module.test_client()
    app_module.testing = False

    for model_dict in models:
        print(f"-------------------------------------------MODEL: {model_dict['model']}-------------------------------------------")
        model = model_dict["model"]
        provider = model_dict["provider"]
        requests_per_minute_limit = model_dict["requests_per_minute_limit"]

        update_settings_table_result = client.post('/api/ai_helper/update_settings_table', json={"model_name": model, "provider": provider, "requests_per_minute_limit": requests_per_minute_limit})
        data = update_settings_table_result.get_json()
        assert data["success"] == True

        for config in ablation_configs:

            for dataset_name in datasets_paths:
                text_cols = dataset_additional_info[dataset_name]["text_cols"]
                identifier_cols = dataset_additional_info[dataset_name]["identifier_cols"]
                print(
                    f"-------------------------------------------CONFIG:  {config["name"]}-------------------------------------------")
                # reset globals living in the app package namespace
                app_module.wrangle_occurred = False

            # reset attributes on the Flask object itself
            app_module.pgraph_for_session = None

            # reset your stateful class instance
            db_operations.reset()

                with open(dataset, 'rb') as f:
                    upload_result = client.post('/api/upload',  data={'file': (f, dataset)},
        content_type='multipart/form-data')
                dataset_path = datasets_paths[dataset_name]
                print(f"-------------------------------------------DATASET:  {dataset_name}-------------------------------------------")
                print(f"Running config {config} wth model {model} and dataset {dataset_name}")

                with open(dataset_path, 'rb') as f:
                    upload_result = client.post('/api/upload', data={'file': (f, dataset_path)},
                                                content_type='multipart/form-data')

                print("ERROR TABLE NAME:", db_operations.error_table_name)
                print("DP TABLE NAME:", db_operations.dp_table_name)
                remove_errors_from_error_table(db_operations.error_table_name, db_operations.main_table_name, text_cols, identifier_cols)
                data = upload_result.get_json()
                assert data["success"] == True


                llm_action_list = []
                ablation_study_result_path = starting_path + f'ablation_study_results' + os.sep + f'ablation_results_{model}_{dataset_name}_{config["name"]}{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.json'

                action_plan_batch = 0

                stop_action_found = False

                while not stop_action_found:
                    action_plan_batch += 1

                    actions = None

                    # Get actions
                    get_action_plan_result = client.post('/api/ai_helper/get_action_plan')
                    action_plan_result_json = get_action_plan_result.get_json()
                    assert action_plan_result_json["success"] == True
                    action_plan_json = action_plan_result_json["json_action_plan"]

                    # Go through all actions and perform each of them
                    for action_dict in action_plan_json:

                        if is_stop_action(action_dict["action_name"]):
                            stop_action_found = True

                        action_result = client.post('/api/ai_helper/perform_llm_action', json=action_dict)
                        remove_errors_from_error_table(db_operations.error_table_name, db_operations.main_table_name,
                                                       text_cols, identifier_cols)
                        action_dict["action_plan_batch"] = action_plan_batch
                        action_dict["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        action_dict["success"] = action_result.get_json()

                        llm_action_list.append(action_dict)

                    # update the ablation study results every 5 actions
                    with open(ablation_study_result_path, 'w') as f:
                        print("UPDATED ABLATION STUDY RESULTS FOR", ablation_study_result_path)
                        json.dump(llm_action_list, f)

                print(f"ABLATION STUDY FOR MODEL {model} DATASET {dataset_name} CONFIG: {config} COMPLETED!!!!!!!!! ")

    print("ABLATION STUDY COMPLETED")






