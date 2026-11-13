"""
UrbanPulse AI - Smart Bin Fill-Level Prediction
Module: ml/src/inference.py
Author: Senior Machine Learning Engineer

Clean inference wrapper for the trained HistGradientBoosting Smart Bin
Fill-Level predictor. Enforces physical domain boundary constraints [0.0, 10.0]
while preserving raw unclipped model outputs for transparent auditing.
"""

from pathlib import Path
from typing import Any, Dict, List, Union
import joblib
import numpy as np
import pandas as pd


class SmartBinPredictor:
    """
    Inference wrapper for the Smart Bin Fill-Level Prediction model.

    Features:
    - Validates feature signature against the trained model bundle.
    - Generates raw continuous predictions from HistGradientBoostingRegressor.
    - Applies domain-aware clipping to guarantee physical validity [0.0, 10.0].
    - Returns both raw and bounded predictions with clipping diagnostic flags.
    """

    MIN_BOUND: float = 0.0
    MAX_BOUND: float = 10.0

    def __init__(self, model_path: Union[str, Path, None] = None):
        if model_path is None:
            # Default to canonical model artifact location
            project_root = self._resolve_project_root()
            model_path = project_root / "ml" / "models" / "smart_bin_fill_predictor.joblib"

        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model bundle not found at: {self.model_path}")

        # Load bundle without modifying the disk artifact
        self.bundle: Dict[str, Any] = joblib.load(self.model_path)
        self.model = self.bundle["model"]
        self.champion_name: str = self.bundle.get("champion_name", "Unknown")
        self.feature_names: List[str] = self.bundle["feature_names"]
        self.target_name: str = self.bundle.get("target_name", "latestFullness")

    @staticmethod
    def _resolve_project_root() -> Path:
        cwd = Path(".").resolve()
        if cwd.name in ["src", "notebooks", "ml", "tests"]:
            for parent in cwd.parents:
                if (parent / "ml").exists() and (parent / "datasets").exists():
                    return parent
        return cwd

    def predict_single(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predict fill level for a single observation dictionary.

        Parameters:
            features: Dictionary containing required feature keys:
                      ['lag_1', 'lag_2', 'lag_3', 'lag_7', 'rolling_mean_3',
                       'rolling_mean_7', 'day_of_week', 'month']

        Returns:
            Dictionary containing:
            - raw_prediction: Unconstrained continuous output from regressor.
            - bounded_prediction: Physically valid fill level clipped to [0.0, 10.0].
            - was_clipped: Boolean indicating whether clipping occurred.
            - clip_direction: 'lower' (if raw < 0), 'upper' (if raw > 10), or 'none'.
            - model_name: Name of estimator producing the forecast.
        """
        # Validate missing features
        missing = [f for f in self.feature_names if f not in features]
        if missing:
            raise ValueError(f"Missing required feature keys in input: {missing}")

        # Format input vector
        input_df = pd.DataFrame([{f: features[f] for f in self.feature_names}])
        raw_val = float(self.model.predict(input_df)[0])
        bounded_val = float(np.clip(raw_val, self.MIN_BOUND, self.MAX_BOUND))

        if raw_val < self.MIN_BOUND:
            clip_dir = "lower"
            was_clipped = True
        elif raw_val > self.MAX_BOUND:
            clip_dir = "upper"
            was_clipped = True
        else:
            clip_dir = "none"
            was_clipped = False

        return {
            "raw_prediction": round(raw_val, 4),
            "bounded_prediction": round(bounded_val, 4),
            "was_clipped": was_clipped,
            "clip_direction": clip_dir,
            "model_name": self.champion_name,
        }

    def predict_batch(self, df_input: pd.DataFrame) -> pd.DataFrame:
        """
        Predict fill levels for a batch pandas DataFrame.

        Parameters:
            df_input: DataFrame containing the required feature columns.

        Returns:
            DataFrame with additional columns:
            - raw_prediction
            - bounded_prediction
            - was_clipped
            - clip_direction
        """
        missing = [f for f in self.feature_names if f not in df_input.columns]
        if missing:
            raise ValueError(f"Missing required feature columns in DataFrame: {missing}")

        X = df_input[self.feature_names]
        raw_vals = self.model.predict(X)
        bounded_vals = np.clip(raw_vals, self.MIN_BOUND, self.MAX_BOUND)

        was_clipped = (raw_vals < self.MIN_BOUND) | (raw_vals > self.MAX_BOUND)
        clip_direction = np.where(
            raw_vals < self.MIN_BOUND,
            "lower",
            np.where(raw_vals > self.MAX_BOUND, "upper", "none"),
        )

        output_df = df_input.copy()
        output_df["raw_prediction"] = raw_vals
        output_df["bounded_prediction"] = bounded_vals
        output_df["was_clipped"] = was_clipped
        output_df["clip_direction"] = clip_direction
        return output_df


if __name__ == "__main__":
    predictor = SmartBinPredictor()
    sample = {
        "lag_1": 6.0,
        "lag_2": 4.0,
        "lag_3": 0.0,
        "lag_7": 2.0,
        "rolling_mean_3": 3.3333,
        "rolling_mean_7": 3.1428,
        "day_of_week": 2,
        "month": 4,
    }
    result = predictor.predict_single(sample)
    print("Single inference test result:")
    print(result)
