from __future__ import annotations
import numpy as np
import pandas as pd


def zscore_mask(
    series: pd.Series,
    z_threshold: float = 3.0,
    min_non_null: int = 10,
    ddof: int = 1,
) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    valid = x.notna()

    if valid.sum() < min_non_null:
        return pd.Series(False, index=series.index)

    mu = x[valid].mean()
    sigma = x[valid].std(ddof=ddof)

    if sigma is None or sigma == 0 or np.isnan(sigma):
        return pd.Series(False, index=series.index)

    z = (x - mu) / sigma
    return (z.abs() > z_threshold).fillna(False)
