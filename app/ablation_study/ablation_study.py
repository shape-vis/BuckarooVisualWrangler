import os

from dotenv import load_dotenv
import datetime


from app import app as app_module
from app import db_operations, engine

import json

from app.db_utils.ai_utils import parse_json_response

datasets_paths = ['provided_datasets/mari_dataset.csv']
#models = [{"model": "qwen/qwen3.6-27b", "provider": "groq"}]
models = [{"model": "openai/gpt-oss-20b", "provider": "groq", "requests_per_minute_limit": 30}]

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

    results = []

    for model_dict in models:

        model = model_dict["model"]
        provider = model_dict["provider"]
        requests_per_minute_limit = model_dict["requests_per_minute_limit"]

        update_settings_table_result = client.post('/api/ai_helper/update_settings_table', json={"model_name": model, "provider": provider, "requests_per_minute_limit": requests_per_minute_limit})
        data = update_settings_table_result.get_json()
        assert data["success"] == True

        for config in ablation_configs:
            # reset globals living in the app package namespace
            app_module.wrangle_occurred = False

            # reset attributes on the Flask object itself
            app_module.pgraph_for_session = None

            # reset your stateful class instance
            db_operations.reset()
            for dataset in datasets_paths:
                print(f"Running config {config} wth model {model} and dataset {dataset}")

                with open(dataset, 'rb') as f:
                    upload_result = client.post('/api/upload',  data={'file': (f, dataset)},
        content_type='multipart/form-data')
                data = upload_result.get_json()
                assert data["success"] == True

                result_dict = {}  # Dict added to the result json
                result_dict["model"] = model_dict
                result_dict["config_name"] = config["name"]
                result_dict["dataset"] = dataset
                result_dict["actions"] = []

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
                        action_dict["action_plan_batch"] = action_plan_batch
                        action_dict["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        action_dict["success"] = action_result.get_json()

                        results.append(action_dict)


    with open(f'ablation_results_{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.json', 'w') as outfile:
        json.dump(results, outfile)


