"""
The upload path (load_file) over generated CSVs: what the database stores is exactly what pandas read from the file -
the COPY stream's quoting, its nulls and its integer columns included - and every row gets its own "ID".
"""
import io
import math

import pandas as pd
import pytest

from tests.stress import generators, reference
from tests.stress.conftest import seeds


def read_like_the_app(text):
    """The file as load_file reads it, before anything of the app's touches it."""
    return pd.read_csv(io.StringIO(text))


def same_cell(read_value, stored_value):
    if reference.is_null(read_value) or reference.is_null(stored_value):
        return reference.is_null(read_value) and reference.is_null(stored_value)
    if isinstance(read_value, (int, float)) and not isinstance(read_value, bool):
        if isinstance(stored_value, str):
            return False
        return math.isclose(float(read_value), float(stored_value), rel_tol=1e-15, abs_tol=0)
    return str(read_value) == str(stored_value)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_an_upload_stores_exactly_what_pandas_read(make_root, seed):
    dataset = generators.make_dataset(seed)
    text = generators.csv_text(dataset)
    read = read_like_the_app(text)

    root = make_root(dataset, ingest="csv")

    assert len(root.frame) == len(read)
    assert root.ids == list(range(1, len(read) + 1))
    for column in read.columns:
        stored_column = column
        if column == "ID":
            stored_column = "Original_ID"
        stored_values = list(root.frame[stored_column])
        read_values = list(read[column])
        for row_index, (read_value, stored_value) in enumerate(zip(read_values, stored_values)):
            assert same_cell(read_value, stored_value), (column, row_index, read_value, stored_value)


@pytest.mark.sql
@pytest.mark.parametrize("ids", [[3, 1, 2], [1, 1, 2], ["a", "b", "c"], [10, 20, 30]])
def test_an_id_column_is_kept_only_when_it_can_name_the_rows(make_root, ids):
    """A numeric, unique ID column names the rows; any other is kept as data, as Original_ID, beside a new one."""
    dataset = generators.Dataset(seed=0, name="with_ids", columns={"ID": ids, "value": [1, 2, 3]})

    root = make_root(dataset, ingest="csv")

    usable = len(set(ids)) == len(ids) and all(isinstance(value, int) for value in ids)
    if usable:
        assert sorted(root.ids) == sorted(ids)
        assert "Original_ID" not in root.frame.columns
    else:
        assert root.ids == [1, 2, 3]
        assert "Original_ID" in root.frame.columns
