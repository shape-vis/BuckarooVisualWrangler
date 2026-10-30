"""
Writes the end-to-end suite's mock datasets and what the app should show for them - October 28, 2026.

    .venv/bin/python -m tests.stress.make_e2e_expected

Each dataset goes to ui/e2e/data/<name>.csv, and its expected values to ui/e2e/data/expected/<name>.json: every
column's error counts and histogram, and for each wrangle the UI tests perform, the wrangled table's histograms,
fill value, drift from root and comparison with its sibling. The values come from the stress tests' answer key
(reference.py), so the UI suite and the backend suite share one source of truth.

The upload is emulated rather than run: the CSV is read as load_file reads it - pandas' reader, set_id_column and the
dtype map that types each column - so the answer key starts from the table the database would hold.
"""
import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import types as sql_types

from app.server_utils.service_helpers import get_sqlalchemy_dtype_map
from app.server_utils.set_id_column import set_id_column
from tests.stress import reference
from tests.stress.reference import StoredTable

DATA_DIR = Path(__file__).resolve().parents[2] / "ui" / "e2e" / "data"
EXPECTED_DIR = DATA_DIR / "expected"


# ── The datasets ─────────────────────────────────────────────────────────────

def tiny_rows():
    """
    12 rows, every value chosen by hand:
        Score     10, 20 ... 100, then two blanks
        Count     1 ... 10, then two blanks - its mean is 5.5, which an integer column stores as 6
        Platform  Wii x5, PS2 x4, PC x3
        Rating    E x5, T x4, M x1, "undefined", and a blank - two missing cells, M and "undefined" rare
    """
    platforms = ["Wii", "Wii", "PS2", "PC", "Wii", "PS2", "PC", "Wii", "PS2", "PC", "Wii", "PS2"]
    ratings = ["E", "E", "T", "E", "T", "M", "E", "T", "E", "T", "undefined", ""]
    rows = []
    for index in range(12):
        score = ""
        count = ""
        if index < 10:
            score = str((index + 1) * 10)
            count = str(index + 1)
        rows.append({"Score": score, "Count": count, "Platform": platforms[index], "Rating": ratings[index]})
    return rows


def games_small_rows():
    """
    300 rows shaped like games.csv: Critic_Score and Critic_Count are blank on the same 60 rows, User_Score is text
    holding numbers and "tbd", Developer has a few rare names.
    """
    rng = random.Random(2026)
    platforms = ["Wii", "PS2", "X360", "PS3", "DS", "PC"]
    genres = ["Sports", "Action", "Racing", "Puzzle", "Shooter"]
    developers = ["Nintendo", "EA Canada", "Ubisoft", "Capcom", "Konami"]
    ratings = ["E", "T", "M", "E10+"]

    blank_rows = set(rng.sample(range(300), 60))
    rows = []
    for index in range(300):
        critic_score = ""
        critic_count = ""
        if index not in blank_rows:
            critic_score = str(rng.randint(30, 95))
            critic_count = str(rng.randint(3, 80))

        user_roll = rng.random()
        if user_roll < 0.08:
            user_score = "tbd"
        elif user_roll < 0.12:
            user_score = ""
        else:
            user_score = f"{rng.uniform(2.0, 9.5):.1f}"

        developer = rng.choice(developers)
        if index in (17, 140):
            developer = "Tiny Studio"
        if index == 251:
            developer = "One Off Games"

        rating = rng.choice(ratings)
        if rng.random() < 0.1:
            rating = ""

        rows.append({
            "Name": f"Game {index + 1:03d}",
            "Platform": rng.choice(platforms),
            "Genre": rng.choice(genres),
            "Critic_Score": critic_score,
            "Critic_Count": critic_count,
            "User_Score": user_score,
            "Developer": developer,
            "Rating": rating,
        })
    return rows


def many_labels_rows():
    """200 rows: Category holds 30 labels and 10 blanks, more than the compare axes and the Sankey keep."""
    rng = random.Random(30)
    rows = []
    for index in range(200):
        category = f"cat_{(index * 7) % 30 + 1:02d}"
        if index % 20 == 0:
            category = ""
        rows.append({"Category": category, "Value": str(rng.randint(1, 50))})
    return rows


def anomalies_rows():
    """
    150 rows: Normal is tight integers with four far outliers; Flat is one value throughout, which nothing can be an
    anomaly of; Mixed is numbers written as text with ten words among them; Label is a plain category.
    """
    rng = random.Random(7)
    outliers = {10: "900", 50: "-400", 90: "1000", 130: "750"}
    rows = []
    for index in range(150):
        normal = outliers.get(index, str(rng.randint(45, 55)))
        mixed = str(rng.randint(1, 20))
        if index % 15 == 0:
            mixed = "n/a"
        rows.append({"Normal": normal, "Flat": "7", "Mixed": mixed, "Label": rng.choice(["alpha", "beta", "gamma"])})
    return rows


DATASETS = {
    "e2e_tiny": tiny_rows,
    "e2e_games_small": games_small_rows,
    "e2e_many_labels": many_labels_rows,
    "e2e_anomalies": anomalies_rows,
}


# ── Reading a CSV as an upload does ──────────────────────────────────────────

def write_csv(name, rows):
    path = DATA_DIR / f"{name}.csv"
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False)
    return path


def stored_table(name, path):
    """The table an upload of this CSV stores, as the answer key reads tables."""
    frame = pd.read_csv(path)
    frame = set_id_column(frame)
    dtype_map = get_sqlalchemy_dtype_map(frame)

    numeric_cols = set()
    text_cols = set()
    integer_cols = set()
    for column, column_type in dtype_map.items():
        if isinstance(column_type, sql_types.Text):
            text_cols.add(column)
        else:
            numeric_cols.add(column)
        if isinstance(column_type, sql_types.BigInteger):
            integer_cols.add(column)

    return table_from_frame(name, frame, numeric_cols, text_cols, integer_cols)


def table_from_frame(name, frame, numeric_cols, text_cols, integer_cols):
    """A StoredTable whose numeric columns are floats with NaN and text columns str or None, as read back from Postgres."""
    stored = {}
    for column in frame.columns:
        values = []
        for value in frame[column]:
            if reference.is_null(value):
                values.append(None)
            elif column in numeric_cols or column == "ID":
                values.append(float(value))
            else:
                values.append(str(value))
        if column in numeric_cols or column == "ID":
            stored[column] = pd.Series(values, dtype="float64")
        else:
            stored[column] = pd.Series(values, dtype="object")
    stored_frame = pd.DataFrame(stored)
    return StoredTable(name=name, frame=stored_frame, numeric_cols=numeric_cols, text_cols=text_cols,
                       integer_cols=integer_cols)


def table_from_rows(parent, name, rows_by_id):
    """A wrangled table, from its rows as reference.delete_rows and impute_rows give them."""
    records = []
    for row_id in sorted(rows_by_id):
        records.append(rows_by_id[row_id])
    frame = pd.DataFrame(records, columns=list(parent.frame.columns))
    return table_from_frame(name, frame, parent.numeric_cols, parent.text_cols, parent.integer_cols)


# ── What the app should show ─────────────────────────────────────────────────

def error_counts(table, flags):
    counts = {}
    for column in table.data_columns:
        counts[column] = {}
        for error_type in reference.ERROR_TYPES:
            counts[column][error_type] = 0
    for _, column, error_type in flags.certain:
        counts[column][error_type] += 1
    return counts


def histogram_json(table, flags, column):
    """One column's main-view histogram, in the shape /api/plots/1-d-histogram sends its bins."""
    result = reference.histogram(table, flags, [column])
    bins = []
    for key, counts in result.bins.items():
        bin_key = key[0]
        bin_type = "categorical"
        if column in table.numeric_cols and bin_key.isdigit():
            bin_type = "numeric"
        bins.append({"xBin": bin_key, "xType": bin_type, "count": counts})

    def bin_order(entry):
        if entry["xType"] == "numeric":
            return 0, int(entry["xBin"]), ""
        return 1, 0, entry["xBin"]

    bins.sort(key=bin_order)
    edges = []
    for x0, x1 in result.numeric_edges:
        edges.append({"x0": x0, "x1": x1})
    return {"bins": bins, "numeric": edges, "labels": result.labels,
            "borderline_rows": sorted(result.borderline_rows)}


def histograms_json(table, flags):
    histograms = {}
    for column in table.data_columns:
        histograms[column] = histogram_json(table, flags, column)
    return histograms


def kinds_of(table):
    kinds = {}
    for column in table.data_columns:
        kinds[column] = table.column_kind(column)
    return kinds


def drift_json(root, node):
    drift = reference.node_drift(root, node, kinds_of(root))
    columns = {}
    for column, result in drift["columns"].items():
        columns[column] = {"value": result["value"], "reason": result["reason"]}
    return {"overall": drift["overall"], "columns": columns}


def compare_json(table_a, table_b, column):
    """Both tables' histograms of one column on shared axes, in the shape /api/pgraph/compare sends its bins."""
    flags_a = reference.detect(table_a)
    flags_b = reference.detect(table_b)
    comparison = reference.compare(table_a, flags_a, table_b, flags_b, [column])
    axis = comparison.axes[0]

    keys = []
    for index in range(axis.bins if axis.is_numeric else 0):
        keys.append(("numeric", index))
    for label in axis.labels_in_order:
        keys.append(("categorical", label))

    bins = []
    for key in keys:
        entry = {"xType": key[0], "xBin": key[1]}
        for side in ("a", "b"):
            counts = comparison.sides[side].get((key,), {"items": 0})
            entry[side] = counts
        bins.append(entry)

    borderline = sorted(comparison.borderline_rows["a"] | comparison.borderline_rows["b"])
    return {"rows": comparison.rows, "bins": bins, "is_numeric": axis.is_numeric, "borderline_rows": borderline}


def node_json(root, table, extra=None):
    flags = reference.detect(table)
    result = {
        "rows": len(table.frame),
        "ids": table.ids,
        "errors": error_counts(table, flags),
        "borderline_flags": len(flags.borderline),
        "histograms": histograms_json(table, flags),
        "drift": drift_json(root, table),
    }
    if extra:
        result.update(extra)
    return result


def missing_ids(table, column):
    ids = []
    for row_id, values in table.rows():
        if reference.is_missing(values[column]):
            ids.append(row_id)
    return ids


def wrangles(root, name, selection_column, row_ids, cols):
    """
    Every candidate a repair of these rows stages, as the app stages them: delete and impute for one column; delete,
    impute x and impute y for two.
    :return: {op: (table, fill or None)}
    """
    deleted = table_from_rows(root, f"{name}_delete", reference.delete_rows(root, row_ids))
    result = {"delete": (deleted, None)}

    impute_ops = [("impute", cols[0])]
    if len(cols) == 2:
        impute_ops = [("impute_x", cols[0]), ("impute_y", cols[1])]
    for op, column in impute_ops:
        integer_column = column in root.integer_cols
        rows, fill = reference.impute_rows(root, column, row_ids, integer_column)
        result[op] = (table_from_rows(root, f"{name}_{op}", rows), fill)
    return result


def scenario_json(root, name, label, row_ids, cols):
    staged = wrangles(root, name, label, row_ids, cols)
    candidates = {}
    for op, (table, fill) in staged.items():
        extra = {"fill": fill}
        candidates[op] = node_json(root, table, extra)
    sibling_compare = {}
    if "impute" in staged:
        deleted = staged["delete"][0]
        imputed = staged["impute"][0]
        for column in root.data_columns:
            sibling_compare[column] = compare_json(deleted, imputed, column)
    return {"row_ids": row_ids, "cols": cols, "candidates": candidates, "delete_vs_impute": sibling_compare}


def scenarios_for(name, root):
    """The wrangles each dataset's UI tests perform."""
    scenarios = {}
    if name == "e2e_tiny":
        scenarios["score_missing"] = scenario_json(root, name, "score", missing_ids(root, "Score"), ["Score"])
        scenarios["count_missing"] = scenario_json(root, name, "count", missing_ids(root, "Count"), ["Count"])
        both = sorted(set(missing_ids(root, "Score")) | set(missing_ids(root, "Count")))
        scenarios["score_count_missing"] = scenario_json(root, name, "pair", both, ["Score", "Count"])
        scenarios["rating_missing"] = scenario_json(root, name, "rating", missing_ids(root, "Rating"), ["Rating"])
    elif name == "e2e_games_small":
        scenarios["critic_count_missing"] = scenario_json(root, name, "cc", missing_ids(root, "Critic_Count"),
                                                          ["Critic_Count"])
    return scenarios


def flows_json(root, node, column):
    flows = []
    for (source, target), rows in sorted(reference.category_flows(root, node, column).items()):
        flows.append({"source": source, "target": target, "rows": rows})
    return flows


def dataset_json(name, root):
    flags = reference.detect(root)
    result = {
        "dataset": name,
        "columns": root.data_columns,
        "kinds": kinds_of(root),
        "numeric_columns": sorted(root.numeric_cols),
        "root": node_json(root, root),
        "scenarios": scenarios_for(name, root),
    }
    if flags.borderline:
        result["warning"] = "borderline anomalies: exact counts are undecidable"
    return result


def to_jsonable(value):
    """numpy and Decimal values as plain JSON."""
    if isinstance(value, dict):
        converted = {}
        for key, item in value.items():
            converted[str(key)] = to_jsonable(item)
        return converted
    if isinstance(value, (list, tuple)):
        converted = []
        for item in value:
            converted.append(to_jsonable(item))
        return converted
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if number.is_integer() and abs(number) < 2 ** 53:
            return number
        return number
    return value


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    for name, make_rows in DATASETS.items():
        path = write_csv(name, make_rows())
        root = stored_table(name, path)
        expected = to_jsonable(dataset_json(name, root))
        expected_path = EXPECTED_DIR / f"{name}.json"
        expected_path.write_text(json.dumps(expected, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.name} ({len(root.frame)} rows) and expected/{expected_path.name}")


if __name__ == "__main__":
    main()
