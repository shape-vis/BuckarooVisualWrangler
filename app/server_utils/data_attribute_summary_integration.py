"""
Converts the current table's attribute summaries into JSON the view can use: each column's error rates and the columns
to show first, read off the node's cached metrics, and each column's summary statistics, read from the data profile.
"""

from app.db_utils.column_types import CATEGORICAL_KIND
from app.db_utils.data_profile import DataProfile
from app.server_utils.service_helpers import session_graph

# How many of the most flagged columns the panel opens on
DEFAULT_ATTRIBUTE_COUNT = 3


def generate_complete_json(tablename):
    """
    Generate a complete JSON representation of the current data state using the whole table.
    :param tablename: name of the table - a node of the session's graph
    :return: JSON representation of the data state
    """
    from app import engine

    if not tablename:
        return {"columnErrors": {}, "attributes": [], "attributeDistributions": {}, "defaultAttributes": []}

    # The node's error rates were measured when it was built, from the same profile
    metrics = session_graph().node_map[tablename].metrics
    data_profile = DataProfile(tablename, engine)

    return {
        "columnErrors": metrics.column_error_rates(),
        "attributes": data_profile.get_col_names(),
        "attributeDistributions": build_attribute_distributions(data_profile),
        "defaultAttributes": metrics.most_flagged_columns(DEFAULT_ATTRIBUTE_COUNT),
    }


def build_attribute_distributions(data_profile):
    """
    Each column's summary statistics, by its kind, in one read of the stored profile.
    :param data_profile: the table's DataProfile
    :return: {column: {"categorical": {"categories", "mode"}}} or {column: {"numeric": {"mean", "min", "max"}}}
    """
    distributions = {}
    for row in data_profile.read_stored_profile():
        column = row["column_name"]
        if data_profile.col_types.column_kind(column) == CATEGORICAL_KIND:
            distributions[column] = {
                "categorical": {
                    "categories": row["n_categories"],
                    "mode": row["mode"],
                }
            }
        else:
            distributions[column] = {
                "numeric": {
                    "mean": row["mean"],
                    "min": row["min"],
                    "max": row["max"],
                }
            }
    return distributions
