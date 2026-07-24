import uuid
from flask import request
import pandas as pd
import traceback

from datetime import datetime, timezone
from sqlalchemy import Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID  # if using Postgres
import logging
import json
logger = logging.getLogger(__name__)

ACTION_LOG_TABLE_NAME = "action_log"

# TODO: this definitely needs to be condensed into a single functon (initializing __ df)
# Just making this as a df to match the format of the other table creation functions
# TODO: switch all of the sql table creation functions to not use pandas because apparently it's very slow
def create_empty_user_action_log_df():
    empty_df = pd.DataFrame(columns=['action_id', 'dataset_id', 'action_name', 'action_details', 'timestamp'])

    return empty_df


# TODO: update documentation
def update_action_log(dataset_id, action_name, action_details, engine):
    try:
        timestamp = datetime.now(timezone.utc)

        if action_details is not None:
            action_details = json.dumps(action_details)

        # Create an action id
        action_id = uuid.uuid4()

        new_action_entry = pd.DataFrame([{"action_id": action_id, "dataset_id": dataset_id, "action_name": action_name, "action_details": action_details, "timestamp": timestamp}])
        new_action_entry.to_sql(ACTION_LOG_TABLE_NAME, engine, if_exists='append', index=False)
    except Exception:
        logger.error("Error updating action log.", exc_info=True)



def initialize_action_log(engine, reset_log=False):
    print("INITIALIZING ACTION LOG")
    dtype_map = {
        'action_id': UUID(as_uuid=True),
        'dataset_id': Text,
        'action_name': Text,
        'action_details': Text,
        'timestamp': TIMESTAMP(timezone=True)
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


