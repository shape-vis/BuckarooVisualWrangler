from __future__ import annotations
import numpy as np
import pandas as pd


def mad_mask(
    series: pd.Series,
    threshold: float = 3.5,
    min_non_null: int = 10,
    center: str = "median",  
    scale: str = "mad",    
    eps: float = 1e-12,
) -> pd.Series:
    """
    MAD-based anomaly detection using the modified z-score idea.

    modified_z = 0.6745 * (x - median) / MAD
    threshold ~ 3.5.

    Returns boolean mask aligned to series.index: True = anomaly.
    """
    x = pd.to_numeric(series, errors="coerce")
    valid = x.notna()

    if valid.sum() < min_non_null:
        return pd.Series(False, index=series.index)

    xv = x[valid]

    if center == "mean":
        c = xv.mean()
    else:
        c = xv.median()

    abs_dev = (xv - c).abs()
    mad = abs_dev.median()

    if mad is None or mad < eps or np.isnan(mad):
        return pd.Series(False, index=series.index)

    modified_z = 0.6745 * (x - c) / mad
    return (modified_z.abs() > threshold).fillna(False)
