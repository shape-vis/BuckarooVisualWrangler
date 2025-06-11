"""
Detector which populates a map of cells which have values that have a z-score
greater than 2
"""
import pandas as pd


def detect_anomaly(dataset):
    dataframe = pd.DataFrame(dataset)