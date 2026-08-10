import uuid
from flask import request
import pandas as pd
import traceback

from datetime import datetime, timezone
from sqlalchemy import Text, TIMESTAMP, Boolean, Float
from sqlalchemy.dialects.postgresql import UUID  # if using Postgres
import logging
import json

from app.db_utils.execute_sql import fetch_sql

logger = logging.getLogger(__name__)

ACTION_LOG_TABLE_NAME = "action_log"
PREVIEW_LOG_TABLE_NAME = "preview_log"

# TODO: switch all of the sql table creation functions to not use pandas because apparently it's very slow
def create_empty_user_action_log_df():
    empty_df = pd.DataFrame(columns=['action_id', 'dataset_id', 'action_name', 'action_details', 'timestamp', 'action_duration', 'action_successful', 'action_error_message'])
    return empty_df

def create_empty_preview_log_df():
    empty_df = pd.DataFrame(columns=['preview_table_name', 'action_name', 'action_details'])
    return empty_df


# TODO: update documentation
def update_action_log(dataset_id, action_name, action_details, engine, timestamp, action_successful,
                      action_duration=None, action_error_message=None):
    try:

        if action_details is not None:
            action_details = json.dumps(action_details)

        # Create an action id
        action_id = uuid.uuid4()
        print("ACTION DURATION TYPE:", type(action_duration))

        new_action_entry = pd.DataFrame([{"action_id": action_id, "dataset_id": dataset_id, "action_name": action_name,
                                          "action_details": action_details, "timestamp": timestamp, "action_duration": action_duration,
                                          "action_successful": action_successful, 'action_error_message': action_error_message}])

        new_action_entry.to_sql(ACTION_LOG_TABLE_NAME, engine, if_exists='append', index=False)
        print("UPDATED ACTION LOG TABLE")
    except Exception:
        logger.error("Error updating action log.", exc_info=True)



def initialize_action_log(engine, reset_log=False):
    print("INITIALIZING ACTION LOG")
    dtype_map = {
        'action_id': UUID(as_uuid=True),
        'dataset_id': Text,
        'action_name': Text,
        'action_details': Text,
        'timestamp': TIMESTAMP,
        'action_duration': Float,
        'action_successful': Boolean,
        'action_error_message': Text
    }

    try:
        empty_log_df = create_empty_user_action_log_df()

        # When we actually can support multiple users, make this name to be user / session specific
        if reset_log:
            empty_log_df.to_sql(ACTION_LOG_TABLE_NAME, engine, if_exists='replace', index=False, dtype=dtype_map)
        else:
            empty_log_df.to_sql(ACTION_LOG_TABLE_NAME, engine, if_exists='append', index=False, dtype=dtype_map)
    except Exception:
        logger.error("Error initializing action log.", exc_info=True)

def initialize_preview_log_table(engine, reset_log=False):
    print("INITIALIZING PREVIEW LOG TABLE")
    dtype_map = {
        'preview_table_name':Text,
        'action_name': Text,
        'action_details': Text
    }

    try:
        empty_log_df = create_empty_preview_log_df()

        if reset_log:
            empty_log_df.to_sql(PREVIEW_LOG_TABLE_NAME, engine, if_exists='replace', index=False, dtype=dtype_map)
        else:
            empty_log_df.to_sql(PREVIEW_LOG_TABLE_NAME, engine, if_exists='append', index=False, dtype=dtype_map)
        print("INITIALIZED PREVIEW LOG TABLE")
    except Exception:
        logger.error("Error initializing preview log table.", exc_info=True)


def update_preview_log(preview_table_name, action_name, action_details, engine):
    try:

        if action_details is not None:
            action_details = json.dumps(action_details)

        new_action_entry = pd.DataFrame([{"preview_table_name": preview_table_name, "action_name": action_name, "action_details": action_details}])
        new_action_entry.to_sql(PREVIEW_LOG_TABLE_NAME, engine, if_exists='append', index=False)
        print("UPDATED PREVIEW LOG TABLE")
    except Exception:
        logger.error("Error updating preview log table.", exc_info=True)

def get_action_details_from_preview_log(preview_table_name, engine):
    try:

        query = f"""
                SELECT action_details 
                FROM "{PREVIEW_LOG_TABLE_NAME}" 
                WHERE preview_table_name = :id
                """

        result = fetch_sql(query, params={"id": preview_table_name},scalar=True, engine=engine)
        return result
    except Exception:
        logger.error(f"Error retrieving action details from {preview_table_name} from preview log.", exc_info=True)
        result = None
        return result






