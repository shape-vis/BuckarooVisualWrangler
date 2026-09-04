
from app import logger
import json

from app.db_utils.execute_sql import fetch_sql, execute_sql


ACTION_LOG_TABLE_NAME = "action_log"
PREVIEW_LOG_TABLE_NAME = "preview_log"

class InvalidActionError(Exception):
    pass

# TODO: update documentation
def update_action_log(main_table_name, action_name, action_details, engine, timestamp, action_success_status,
                      llm_suggested, action_duration=None, action_error_message=None, reset_log=False):
    """
    Updates the action log table
    :param main_table_name: the name of the dataset that the action was performed on
    :param action_name: the name of the action that was performed
    :param action_details: a dictionary of details about the action that was performed
    :param engine: the database engine
    :param timestamp: the timestamp of when the action was performed
    :param action_success_status:
    :param action_duration: the duration of the action in seconds
    :param action_error_message: the error message if the action was not successful
    :param reset_log: whether to reset the action log table
    :return: None
    """


    try:

        if action_details is not None:
            action_details = json.dumps(action_details)

        if reset_log:
            execute_sql(f"DROP TABLE IF EXISTS {ACTION_LOG_TABLE_NAME}", engine)

        execute_sql(f"""
                               CREATE TABLE IF NOT EXISTS {ACTION_LOG_TABLE_NAME}
                               (
                                    action_id
                                   SERIAL
                                   PRIMARY
                                   KEY
                                   ,
                                   dataset_id
                                   TEXT
                                   NOT
                                   NULL,
                                   action_name
                                   TEXT
                                   NOT
                                   NULL,
                                   action_details
                                   TEXT,
                                   "timestamp"
                                    TIMESTAMP,
                                    action_duration
                                    FLOAT,
                                    action_successful
                                    TEXT
                                    NOT NULL,
                                    llm_suggested
                                    BOOLEAN,
                                    action_error_message
                                    TEXT
                               )
                               """, engine)

        execute_sql(
            f"INSERT INTO {ACTION_LOG_TABLE_NAME} (dataset_id, action_name, action_details, timestamp, action_duration, action_successful, llm_suggested, action_error_message) VALUES (:dataset_id, :action_name, :action_details, :timestamp, :action_duration, :action_successful, :llm_suggested, :action_error_message)",
            engine, {"dataset_id": main_table_name, "action_name": action_name, "action_details": action_details, "timestamp": timestamp, "action_duration": action_duration, "action_successful": action_success_status, "llm_suggested":llm_suggested, "action_error_message": action_error_message}
        )

        print("UPDATED ACTION LOG TABLE")
    except Exception as e:
        logger.exception("Error updating action log table.")




def update_preview_log(preview_table_name, action_name, action_details, engine, reset_log=False):
    """
    Updates the preview log table
    :param preview_table_name: the name of the preview table
    :param action_name: the name of the action that was performed
    :param action_details: a dictionary of details about the action that was performed
    :param engine: the database engine
    :param reset_log: whether to reset the action log table
    :return: None
    """
    try:

        if action_details is not None:
            action_details = json.dumps(action_details)

        if reset_log:
            execute_sql(f"DROP TABLE IF EXISTS {PREVIEW_LOG_TABLE_NAME}", engine)


        execute_sql(f"""
                                      CREATE TABLE IF NOT EXISTS {PREVIEW_LOG_TABLE_NAME}
                                      (
                                           preview_table_name
                                          TEXT
                                          PRIMARY
                                          KEY,
                                          action_name
                                          TEXT
                                          NOT
                                          NULL,
                                          action_details
                                          TEXT
                                      )
                                      """, engine)

        execute_sql(
            f"INSERT INTO {PREVIEW_LOG_TABLE_NAME} (preview_table_name, action_name, action_details) VALUES (:preview_table_name, :action_name, :action_details)"
            f"ON CONFLICT (preview_table_name) DO UPDATE SET action_name = EXCLUDED.action_name, action_details = EXCLUDED.action_details",
            engine, {"preview_table_name": preview_table_name, "action_name": action_name, "action_details": action_details}
        )

        print("UPDATED PREVIEW LOG TABLE")
    except Exception:
        logger.exception("Error updating preview log table.")

def get_action_details_from_preview_log(preview_table_name, engine):
    """
    Gets the action details of the preview_table from the preview log table
    :param preview_table_name: the name of the preview table
    :param engine: the database engine
    """
    try:

        query = f"""
                SELECT action_details 
                FROM "{PREVIEW_LOG_TABLE_NAME}" 
                WHERE preview_table_name = :id
                """

        result = fetch_sql(query, params={"id": preview_table_name},scalar=True, engine=engine)
        return result
    except Exception:
        logger.exception(f"Error retrieving action details from {preview_table_name} from preview log.")
        result = None
        return result






