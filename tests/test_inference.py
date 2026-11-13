"""
Unit test suite for the SmartBinPredictor inference wrapper.
Validates boundary constraints [0.0, 10.0], preservation of raw outputs,
clipping behavior, and metric improvements on the test set.
"""

import sys
from pathlib import Path

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parents[1]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

from ml.src.inference import SmartBinPredictor


@pytest.fixture
def predictor():
    return SmartBinPredictor()


@pytest.fixture
def test_dataset():
    csv_path = root_dir / "datasets" / "processed" / "smart_bin_cleaned.csv"
    df = pd.read_csv(csv_path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    df["lag_1"] = df["latestFullness"].shift(1)
    df["lag_2"] = df["latestFullness"].shift(2)
    df["lag_3"] = df["latestFullness"].shift(3)
    df["lag_7"] = df["latestFullness"].shift(7)
    df["rolling_mean_3"] = df["latestFullness"].shift(1).rolling(3).mean()
    df["rolling_mean_7"] = df["latestFullness"].shift(1).rolling(7).mean()
    df["day_of_week"] = df["datetime"].dt.dayofweek
    df["month"] = df["datetime"].dt.month

    df_model = df.dropna().reset_index(drop=True)
    split_idx = int(len(df_model) * 0.8)
    return df_model.iloc[split_idx:].copy()


def test_single_prediction_validity(predictor):
    sample = {
        "lag_1": 4.0,
        "lag_2": 2.0,
        "lag_3": 0.0,
        "lag_7": 6.0,
        "rolling_mean_3": 2.0,
        "rolling_mean_7": 3.14,
        "day_of_week": 4,
        "month": 5,
    }
    res = predictor.predict_single(sample)
    assert "raw_prediction" in res
    assert "bounded_prediction" in res
    assert "was_clipped" in res
    assert 0.0 <= res["bounded_prediction"] <= 10.0


def test_clipping_on_negative_producing_input(predictor):
    # Historical input from 2020-04-19 where raw prediction was -0.7755
    sample_negative = {
        "lag_1": 6.0,
        "lag_2": 4.0,
        "lag_3": 0.0,
        "lag_7": 0.0,
        "rolling_mean_3": 4.6667,
        "rolling_mean_7": 3.4286,
        "day_of_week": 6,
        "month": 4,
    }
    res = predictor.predict_single(sample_negative)
    assert res["raw_prediction"] < 0.0, "Expected negative raw prediction"
    assert res["bounded_prediction"] == 0.0, "Expected bounded prediction to clamp to 0.0"
    assert res["was_clipped"] is True
    assert res["clip_direction"] == "lower"


def test_batch_prediction_bounds_on_test_set(predictor, test_dataset):
    df_pred = predictor.predict_batch(test_dataset)

    # 1. Bounded predictions must strictly remain within [0.0, 10.0]
    assert (df_pred["bounded_prediction"] >= 0.0).all(), "Found bounded predictions < 0"
    assert (df_pred["bounded_prediction"] <= 10.0).all(), "Found bounded predictions > 10"

    # 2. Raw predictions must preserve unclipped values
    raw_min = df_pred["raw_prediction"].min()
    assert raw_min < 0.0, f"Expected raw predictions to drop below 0, got {raw_min}"

    # 3. Exactly 10 predictions were clipped in the test set
    clipped_count = df_pred["was_clipped"].sum()
    assert clipped_count == 10, f"Expected 10 clipped test predictions, got {clipped_count}"

    # 4. In all 10 clipped instances, actual target was 0.0
    clipped_rows = df_pred[df_pred["was_clipped"]]
    assert (clipped_rows["latestFullness"] == 0.0).all()


def test_metric_comparison(predictor, test_dataset):
    df_pred = predictor.predict_batch(test_dataset)
    y_true = df_pred["latestFullness"]
    y_raw = df_pred["raw_prediction"]
    y_bounded = df_pred["bounded_prediction"]

    raw_mae = mean_absolute_error(y_true, y_raw)
    bounded_mae = mean_absolute_error(y_true, y_bounded)
    bounded_rmse = root_mean_squared_error(y_true, y_bounded)
    bounded_r2 = r2_score(y_true, y_bounded)

    # Clamped predictions must improve MAE, RMSE, and R2 because ground truth was 0.0
    assert bounded_mae < raw_mae
    assert np.isclose(bounded_mae, 1.297485, atol=1e-5)
    assert np.isclose(bounded_rmse, 1.618479, atol=1e-5)
    assert np.isclose(bounded_r2, 0.489498, atol=1e-5)
