"""
UrbanPulse AI - Smart Bin Service
Module: backend/services/bin_service.py
Author: Senior Python Backend Engineer

Manages prototype bin metadata, historical time-series feature construction,
and delegates prediction requests to the SmartBinPredictor.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from fastapi import HTTPException, status

from ml.src.inference import SmartBinPredictor


class BinService:
    """
    Service layer for managing Smart Bin entities and ML inference.
    """

    PROTOTYPE_BIN_ID = "BIN-PROTOTYPE-01"

    def __init__(self, data_csv_path: Optional[Path] = None, predictor: Optional[SmartBinPredictor] = None):
        self.root = self._resolve_project_root()
        if data_csv_path is None:
            data_csv_path = self.root / "datasets" / "processed" / "smart_bin_cleaned.csv"
        self.data_csv_path = Path(data_csv_path)

        # Initialize predictor instance
        if predictor is None:
            self.predictor = SmartBinPredictor()
        else:
            self.predictor = predictor

        # Load historical observations
        self._df_history = self._load_historical_data()

    def _resolve_project_root(self) -> Path:
        cwd = Path(".").resolve()
        if cwd.name in ["backend", "services", "api", "ml", "notebooks", "tests"]:
            for parent in cwd.parents:
                if (parent / "backend").exists() and (parent / "datasets").exists():
                    return parent
        return cwd

    def _load_historical_data(self) -> pd.DataFrame:
        """Load and sort the cleaned historical dataset."""
        if not self.data_csv_path.exists():
            raise FileNotFoundError(f"Cleaned dataset not found at: {self.data_csv_path}")
        df = pd.read_csv(self.data_csv_path)
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df.sort_values("datetime").reset_index(drop=True)

    def get_model_status(self) -> Dict[str, Any]:
        """Return operational status of the ML model."""
        return {
            "loaded": self.predictor.model is not None,
            "model_name": self.predictor.champion_name,
            "target_name": self.predictor.target_name,
            "features": self.predictor.feature_names,
        }

    def get_available_bins(self) -> List[Dict[str, Any]]:
        """
        List all available bins.
        Accurately reports single research prototype bin without simulating fake bins.
        """
        latest_date = self._df_history["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")
        latest_fill = float(self._df_history["latestFullness"].iloc[-1])

        bin_data = {
            "bin_id": self.PROTOTYPE_BIN_ID,
            "name": "Smart Waste Bin (Research Prototype)",
            "waste_type": "General Waste",
            "capacity_liters": 120,
            "status": "active_historical_sample",
            "data_source": "Research Dataset (Smart Bin Insights, 2018-2020)",
            "total_historical_records": len(self._df_history),
            "latest_reading_date": latest_date,
            "latest_recorded_fill_level": latest_fill,
            "fill_level_scale": "0 to 10 (0=Empty, 10=Full)",
            "notes": (
                "Prototype representing single-bin historical telemetry. "
                "Not connected to live physical IoT hardware."
            ),
        }
        return [bin_data]

    def get_bin_by_id(self, bin_id: str) -> Dict[str, Any]:
        """Fetch prototype bin details by ID, or raise 404."""
        if bin_id.upper() != self.PROTOTYPE_BIN_ID:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Bin '{bin_id}' was not found. Valid prototype ID is '{self.PROTOTYPE_BIN_ID}'.",
            )
        return self.get_available_bins()[0]

    def predict_fill_level(self, bin_id: str) -> Dict[str, Any]:
        """
        Construct the latest historical feature vector and generate fill-level forecast.
        """
        # 1. Validate bin ID
        bin_info = self.get_bin_by_id(bin_id)

        # 2. Validate historical observation sufficiency (minimum 7 rows for lag_7 and rolling_mean_7)
        if len(self._df_history) < 7:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Insufficient historical observations to construct 7-day lookback features.",
            )

        # 3. Construct feature inputs from the latest available observations
        last_date = self._df_history["datetime"].iloc[-1]
        forecast_date = last_date + pd.Timedelta(days=1)

        features_used = {
            "lag_1": float(self._df_history["latestFullness"].iloc[-1]),
            "lag_2": float(self._df_history["latestFullness"].iloc[-2]),
            "lag_3": float(self._df_history["latestFullness"].iloc[-3]),
            "lag_7": float(self._df_history["latestFullness"].iloc[-7]),
            "rolling_mean_3": float(self._df_history["latestFullness"].iloc[-3:].mean()),
            "rolling_mean_7": float(self._df_history["latestFullness"].iloc[-7:].mean()),
            "day_of_week": int(forecast_date.dayofweek),
            "month": int(forecast_date.month),
        }

        # 4. Generate prediction via SmartBinPredictor
        try:
            pred_result = self.predictor.predict_single(features_used)
        except Exception as e:
            # Shield internal stack traces
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Prediction engine failed to process the feature inputs.",
            )

        # 5. Build clean, structured response
        return {
            "bin_id": bin_info["bin_id"],
            "prediction_timestamp": forecast_date.strftime("%Y-%m-%d %H:%M:%S"),
            "forecast_horizon": "Next calendar observation (+1 day)",
            "raw_prediction": pred_result["raw_prediction"],
            "bounded_prediction": pred_result["bounded_prediction"],
            "was_clipped": pred_result["was_clipped"],
            "clip_direction": pred_result["clip_direction"],
            "model_name": pred_result["model_name"],
            "unit_range": "0–10",
            "historical_base_date": last_date.strftime("%Y-%m-%d %H:%M:%S"),
            "features_used": features_used,
        }


# Singleton service instance for route dependency injection
_bin_service_instance: Optional[BinService] = None


def get_bin_service() -> BinService:
    global _bin_service_instance
    if _bin_service_instance is None:
        _bin_service_instance = BinService()
    return _bin_service_instance
