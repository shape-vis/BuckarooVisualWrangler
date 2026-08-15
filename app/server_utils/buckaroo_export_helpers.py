"""Buckaroo export helper library.

This module is shipped alongside every generated Buckaroo export script. The
export script imports the helpers below instead of redefining them inline, so
the boilerplate lives in exactly one place.

Buckaroo export assumptions:
- If the input CSV already has a stable ID column, row operations match by ID
  and tolerate row reordering, inserted unrelated rows, deleted unrelated rows,
  and appended rows.
- If the input CSV has no ID column, this script recreates Buckaroo's generated
  IDs from row order. In that case, appending rows after the original data is
  supported, but inserting/deleting/reordering rows before edited rows can
  change generated IDs and may target different rows.
- Delete-row skips IDs that are no longer present.
- Impute fills selected IDs for the target column. Buckaroo stores only the row
  IDs that were flagged for that column, so non-error selections stay untouched
  before they reach the export script.
- Delete-column ignores columns that are already absent.
"""

import pandas as pd

MISSING_TOKENS = {'', 'null', 'undefined', 'nan', 'none'}


def buckaroo_ensure_id(df):
    """Match Buckaroo's row identity convention when the source has no ID."""
    if 'ID' not in df.columns:
        df = df.copy()
        df.insert(0, 'ID', range(1, len(df) + 1))
    return df


def buckaroo_missing_mask(series):
    """Return True for nulls and common string spellings of missing values."""
    return series.isna() | series.astype(str).str.strip().str.lower().isin(MISSING_TOKENS)


def buckaroo_imputation_value(series):
    """Use the numeric mean when possible, otherwise the categorical mode."""
    missing = buckaroo_missing_mask(series)
    valid = series[~missing]
    numeric = pd.to_numeric(valid, errors='coerce')
    if len(valid) > 0 and numeric.notna().sum() == len(valid):
        return numeric.mean()
    mode = valid.mode()
    return mode.iloc[0] if not mode.empty else None


def buckaroo_delete_rows_by_id(df, row_ids):
    """Delete rows by Buckaroo ID. Missing IDs are harmless."""
    return df[~df['ID'].isin(row_ids)].copy()


def buckaroo_impute_missing_by_id(df, row_ids, column):
    """Fill selected flagged cells in one column."""
    if column not in df.columns:
        return df
    target = df['ID'].isin(row_ids)
    if not target.any():
        return df
    fill_value = buckaroo_imputation_value(df[column])
    if fill_value is None:
        # No valid value to impute from (e.g. the whole column is missing).
        # Leave the cells untouched instead of writing NaN over them.
        return df
    df = df.copy()
    df.loc[target, column] = fill_value
    return df


def buckaroo_delete_column(df, column):
    """Delete an attribute while preserving Buckaroo's required ID column."""
    if column == 'ID':
        return df
    return df.drop(columns=[column], errors='ignore')
