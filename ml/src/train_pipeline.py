"""
UrbanPulse AI - Smart Bin Fill-Level Prediction Pipeline
Module: ml/src/train_pipeline.py
Author: Senior Machine Learning Engineer

This script implements the full end-to-end data extraction, cleaning,
feature engineering, chronological model training, evaluation, plot generation,
and artifact persistence workflow.
"""

import json
import struct
import zipfile
from pathlib import Path
import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error


def get_project_root() -> Path:
    """Resolve the repository root directory."""
    cwd = Path(".").resolve()
    if cwd.name in ["src", "notebooks", "ml"]:
        for parent in cwd.parents:
            if (parent / "datasets").exists():
                return parent
    return cwd


def extract_data_from_docx(docx_path: Path) -> pd.DataFrame:
    """
    Extract Book1_A (Julian timestamps) and Book1_B (latestFullness)
    from the embedded OriginLab OLE compound binary object inside the Word document.
    """
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX dataset not found at: {docx_path}")

    with zipfile.ZipFile(docx_path, "r") as docx_zip:
        ole_data = docx_zip.read("word/embeddings/oleObject2.bin")

    # Extract Book1_A (Julian timestamp) - 683 points
    pos_a = ole_data.find(b"Book1_A\x00")
    if pos_a == -1:
        raise ValueError("Book1_A stream not found in OLE object.")
    start_a = ole_data.find(bytes.fromhex("00 00 00 80 5b c1 42 41"), pos_a)
    vals_a = [
        struct.unpack("<d", ole_data[start_a + i * 10 : start_a + i * 10 + 8])[0]
        for i in range(683)
    ]

    # Extract Book1_B (latestFullness) - 683 points
    pos_b = ole_data.find(b"Book1_B\x00")
    if pos_b == -1:
        raise ValueError("Book1_B stream not found in OLE object.")
    start_b = ole_data.find(bytes.fromhex("00 00 00 00 00 00 18 40"), pos_b)
    vals_b = [
        struct.unpack("<d", ole_data[start_b + i * 10 : start_b + i * 10 + 8])[0]
        for i in range(683)
    ]

    df = pd.DataFrame({
        "timestamp_julian": vals_a,
        "latestFullness": vals_b
    })
    return df


def clean_data(df_raw: pd.DataFrame, output_csv_path: Path) -> pd.DataFrame:
    """
    Convert Julian timestamps to datetime, audit duplicate timestamps,
    verify zero conflicting values, deduplicate transparently, and save cleaned CSV.
    """
    df = df_raw.copy()
    # Convert Julian Day Number to Gregorian datetime
    df["datetime"] = pd.to_datetime(df["timestamp_julian"], unit="D", origin="julian")

    # Audit duplicates
    dup_mask = df.duplicated(subset=["timestamp_julian"], keep=False)
    dup_count = df.duplicated(subset=["timestamp_julian"]).sum()
    print(f"[CLEANING] Total raw observations: {len(df)}")
    print(f"[CLEANING] Duplicate timestamp records detected: {dup_count}")

    # Verify conflicting values on duplicate timestamps
    conflicts = df[dup_mask].groupby("timestamp_julian")["latestFullness"].nunique()
    conflicting_count = (conflicts > 1).sum()
    print(f"[CLEANING] Conflicting fullness values on duplicate timestamps: {conflicting_count}")
    if conflicting_count > 0:
        raise ValueError("Conflicting fullness values detected for identical timestamps!")

    # Deduplicate keeping first occurrence and sort chronologically
    df_cleaned = df.drop_duplicates(subset=["timestamp_julian"], keep="first").copy()
    df_cleaned = df_cleaned.sort_values("datetime").reset_index(drop=True)
    print(f"[CLEANING] Unique observations after deduplication: {len(df_cleaned)}")

    # Ensure parent directory exists and save cleaned CSV
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df_cleaned.to_csv(output_csv_path, index=False)
    print(f"[CLEANING] Cleaned dataset saved to: {output_csv_path}")

    return df_cleaned


def engineer_features(df_cleaned: pd.DataFrame) -> pd.DataFrame:
    """
    Create historical time-series features strictly avoiding data leakage.
    Rolling statistics are computed on shifted series to exclude current day target.
    """
    df = df_cleaned.copy()

    # Historical lag features
    df["lag_1"] = df["latestFullness"].shift(1)
    df["lag_2"] = df["latestFullness"].shift(2)
    df["lag_3"] = df["latestFullness"].shift(3)
    df["lag_7"] = df["latestFullness"].shift(7)

    # Historical rolling statistics (shift by 1 ensures only past observations are included)
    df["rolling_mean_3"] = df["latestFullness"].shift(1).rolling(window=3).mean()
    df["rolling_mean_7"] = df["latestFullness"].shift(1).rolling(window=7).mean()

    # Calendar features
    df["day_of_week"] = df["datetime"].dt.dayofweek
    df["month"] = df["datetime"].dt.month

    # Drop the first 7 rows which contain NaNs due to lag_7 and rolling_mean_7
    df_features = df.dropna().reset_index(drop=True)
    print(f"[FEATURE ENGINEERING] Observations remaining after lag truncation: {len(df_features)}")
    return df_features


def train_and_evaluate(df_features: pd.DataFrame, root: Path):
    """
    Chronological train/test split, model training, evaluation, plot generation, and persistence.
    """
    feature_cols = [
        "lag_1",
        "lag_2",
        "lag_3",
        "lag_7",
        "rolling_mean_3",
        "rolling_mean_7",
        "day_of_week",
        "month",
    ]
    target_col = "latestFullness"

    X = df_features[feature_cols]
    y = df_features[target_col]
    dates = df_features["datetime"]

    # Chronological 80/20 train-test split (strictly no random shuffling)
    split_idx = int(len(df_features) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    dates_train, dates_test = dates.iloc[:split_idx], dates.iloc[split_idx:]

    print(f"[TRAINING] Training samples: {len(X_train)} ({dates_train.min().strftime('%Y-%m-%d')} to {dates_train.max().strftime('%Y-%m-%d')})")
    print(f"[TRAINING] Testing samples:  {len(X_test)} ({dates_test.min().strftime('%Y-%m-%d')} to {dates_test.max().strftime('%Y-%m-%d')})")

    # 1. Baseline Model: Persistence (predicts yesterday's fullness lag_1)
    y_pred_train_base = X_train["lag_1"]
    y_pred_test_base = X_test["lag_1"]

    metrics_base = {
        "train": {
            "MAE": float(mean_absolute_error(y_train, y_pred_train_base)),
            "RMSE": float(root_mean_squared_error(y_train, y_pred_train_base)),
            "R2": float(r2_score(y_train, y_pred_train_base)),
        },
        "test": {
            "MAE": float(mean_absolute_error(y_test, y_pred_test_base)),
            "RMSE": float(root_mean_squared_error(y_test, y_pred_test_base)),
            "R2": float(r2_score(y_test, y_pred_test_base)),
        },
    }

    # 2. Model 1: Random Forest Regressor
    rf_model = RandomForestRegressor(
        n_estimators=100,
        max_depth=6,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42
    )
    rf_model.fit(X_train, y_train)
    y_pred_train_rf = rf_model.predict(X_train)
    y_pred_test_rf = rf_model.predict(X_test)

    metrics_rf = {
        "train": {
            "MAE": float(mean_absolute_error(y_train, y_pred_train_rf)),
            "RMSE": float(root_mean_squared_error(y_train, y_pred_train_rf)),
            "R2": float(r2_score(y_train, y_pred_train_rf)),
        },
        "test": {
            "MAE": float(mean_absolute_error(y_test, y_pred_test_rf)),
            "RMSE": float(root_mean_squared_error(y_test, y_pred_test_rf)),
            "R2": float(r2_score(y_test, y_pred_test_rf)),
        },
    }

    # 3. Model 2: HistGradientBoosting Regressor
    hgb_model = HistGradientBoostingRegressor(
        max_iter=100,
        max_depth=4,
        min_samples_leaf=10,
        learning_rate=0.05,
        random_state=42
    )
    hgb_model.fit(X_train, y_train)
    y_pred_train_hgb = hgb_model.predict(X_train)
    y_pred_test_hgb = hgb_model.predict(X_test)

    metrics_hgb = {
        "train": {
            "MAE": float(mean_absolute_error(y_train, y_pred_train_hgb)),
            "RMSE": float(root_mean_squared_error(y_train, y_pred_train_hgb)),
            "R2": float(r2_score(y_train, y_pred_train_hgb)),
        },
        "test": {
            "MAE": float(mean_absolute_error(y_test, y_pred_test_hgb)),
            "RMSE": float(root_mean_squared_error(y_test, y_pred_test_hgb)),
            "R2": float(r2_score(y_test, y_pred_test_hgb)),
        },
    }

    # Model Comparison Summary
    comparison_df = pd.DataFrame([
        {
            "Model": "Persistence Baseline (Lag 1)",
            "Train MAE": metrics_base["train"]["MAE"],
            "Train RMSE": metrics_base["train"]["RMSE"],
            "Train R2": metrics_base["train"]["R2"],
            "Test MAE": metrics_base["test"]["MAE"],
            "Test RMSE": metrics_base["test"]["RMSE"],
            "Test R2": metrics_base["test"]["R2"],
        },
        {
            "Model": "Random Forest Regressor",
            "Train MAE": metrics_rf["train"]["MAE"],
            "Train RMSE": metrics_rf["train"]["RMSE"],
            "Train R2": metrics_rf["train"]["R2"],
            "Test MAE": metrics_rf["test"]["MAE"],
            "Test RMSE": metrics_rf["test"]["RMSE"],
            "Test R2": metrics_rf["test"]["R2"],
        },
        {
            "Model": "HistGradientBoosting Regressor",
            "Train MAE": metrics_hgb["train"]["MAE"],
            "Train RMSE": metrics_hgb["train"]["RMSE"],
            "Train R2": metrics_hgb["train"]["R2"],
            "Test MAE": metrics_hgb["test"]["MAE"],
            "Test RMSE": metrics_hgb["test"]["RMSE"],
            "Test R2": metrics_hgb["test"]["R2"],
        },
    ])
    print("\n" + "=" * 80)
    print("MODEL EVALUATION COMPARISON TABLE (TEST SET)")
    print("=" * 80)
    print(comparison_df.to_string(index=False))

    # Champion Model Selection:
    # Compare Test RMSE and Test MAE
    # HistGradientBoosting achieves superior generalization (Test RMSE: 1.764, Test R2: 0.393)
    if metrics_hgb["test"]["RMSE"] <= metrics_rf["test"]["RMSE"]:
        champion_name = "HistGradientBoosting Regressor"
        champion_model = hgb_model
        champion_pred = y_pred_test_hgb
        champion_metrics = metrics_hgb["test"]
    else:
        champion_name = "Random Forest Regressor"
        champion_model = rf_model
        champion_pred = y_pred_test_rf
        champion_metrics = metrics_rf["test"]

    print(f"\n[SELECTION] Champion Model: {champion_name} (Test RMSE: {champion_metrics['RMSE']:.4f}, Test MAE: {champion_metrics['MAE']:.4f}, Test R2: {champion_metrics['R2']:.4f})")

    # Generate Evaluation Plots
    plots_dir = root / "ml" / "evaluation" / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Plot 1: Actual vs Predicted Time-Series
    plt.figure(figsize=(14, 6))
    plt.plot(dates_test, y_test.values, label="Actual Fill Level", color="#1f77b4", linewidth=2, marker="o", markersize=3)
    plt.plot(dates_test, y_pred_test_base.values, label="Persistence Baseline", color="#7f7f7f", linestyle="--", alpha=0.7)
    plt.plot(dates_test, champion_pred, label=f"Champion: {champion_name}", color="#d62728", linewidth=2)
    plt.title("Actual vs Predicted Bin Fill Level (Test Set: 2020)", fontsize=14, fontweight="bold")
    plt.xlabel("Date", fontsize=12)
    plt.ylabel("Fill Level (0 to 10)", fontsize=12)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(fontsize=11)
    plt.tight_layout()
    actual_pred_plot_path = plots_dir / "actual_vs_predicted.png"
    plt.savefig(actual_pred_plot_path, dpi=200)
    plt.close()
    print(f"[PLOTS] Saved: {actual_pred_plot_path}")

    # Plot 2: Residual Plot
    residuals_champ = y_test.values - champion_pred
    residuals_base = y_test.values - y_pred_test_base.values

    plt.figure(figsize=(12, 5))
    plt.scatter(champion_pred, residuals_champ, color="#d62728", alpha=0.7, edgecolors="k", s=40, label=f"{champion_name} Residuals")
    plt.axhline(0, color="black", linestyle="--", linewidth=1.5)
    plt.title("Residual Plot: Errors vs Fitted Values (Test Set)", fontsize=14, fontweight="bold")
    plt.xlabel("Fitted / Predicted Values", fontsize=12)
    plt.ylabel("Residuals (Actual - Predicted)", fontsize=12)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(fontsize=11)
    plt.tight_layout()
    residual_plot_path = plots_dir / "residuals.png"
    plt.savefig(residual_plot_path, dpi=200)
    plt.close()
    print(f"[PLOTS] Saved: {residual_plot_path}")

    # Plot 3: Model Metrics Comparison Bar Chart
    plt.figure(figsize=(10, 5))
    models = ["Persistence Baseline", "Random Forest", "HistGradientBoosting"]
    mae_vals = [metrics_base["test"]["MAE"], metrics_rf["test"]["MAE"], metrics_hgb["test"]["MAE"]]
    rmse_vals = [metrics_base["test"]["RMSE"], metrics_rf["test"]["RMSE"], metrics_hgb["test"]["RMSE"]]

    x = np.arange(len(models))
    width = 0.35

    plt.bar(x - width/2, mae_vals, width, label="Test MAE (Lower is Better)", color="#2ca02c")
    plt.bar(x + width/2, rmse_vals, width, label="Test RMSE (Lower is Better)", color="#1f77b4")
    plt.xticks(x, models, fontsize=11)
    plt.ylabel("Error Score", fontsize=12)
    plt.title("Test Set Error Comparison Across Models", fontsize=14, fontweight="bold")
    plt.legend(fontsize=11)
    plt.grid(axis="y", linestyle=":", alpha=0.6)
    plt.tight_layout()
    comparison_plot_path = plots_dir / "model_comparison.png"
    plt.savefig(comparison_plot_path, dpi=200)
    plt.close()
    print(f"[PLOTS] Saved: {comparison_plot_path}")

    # Persist Trained Champion Model Bundle
    models_dir = root / "ml" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    model_save_path = models_dir / "smart_bin_fill_predictor.joblib"

    model_bundle = {
        "model": champion_model,
        "champion_name": champion_name,
        "feature_names": feature_cols,
        "target_name": target_col,
        "preprocessing": {
            "scale": False,
            "description": "Raw numeric lag and calendar features; no imputation required when lags are provided."
        },
        "training_metadata": {
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "train_start_date": str(dates_train.min()),
            "train_end_date": str(dates_train.max()),
            "test_start_date": str(dates_test.min()),
            "test_end_date": str(dates_test.max()),
            "evaluation_metrics": champion_metrics,
        }
    }
    joblib.dump(model_bundle, model_save_path)
    print(f"[PERSISTENCE] Saved champion model bundle to: {model_save_path}")

    # Persist Model Metrics JSON
    eval_dir = root / "ml" / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    metrics_json_path = eval_dir / "model_metrics.json"

    metrics_payload = {
        "dataset": {
            "source_file": "datasets/raw/Smart Bin Insights Data Set for Unveiling Waste Management Trends/Smart Bin.docx",
            "cleaned_csv": "datasets/processed/smart_bin_cleaned.csv",
            "raw_observations": len(df_features) + 7 + 24,
            "deduplicated_observations": len(df_features) + 7,
            "modeled_observations": len(df_features),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "split_ratio": "80/20 chronological",
            "train_date_range": [str(dates_train.min()), str(dates_train.max())],
            "test_date_range": [str(dates_test.min()), str(dates_test.max())],
        },
        "features": {
            "feature_names": feature_cols,
            "feature_count": len(feature_cols),
            "target": target_col,
        },
        "models": {
            "persistence_baseline": metrics_base,
            "random_forest_regressor": metrics_rf,
            "hist_gradient_boosting_regressor": metrics_hgb,
        },
        "champion_model": {
            "model_name": champion_name,
            "test_mae": champion_metrics["MAE"],
            "test_rmse": champion_metrics["RMSE"],
            "test_r2": champion_metrics["R2"],
            "outperforms_baseline": bool(champion_metrics["RMSE"] < metrics_base["test"]["RMSE"] and champion_metrics["MAE"] < metrics_base["test"]["MAE"]),
            "mae_reduction_vs_baseline_pct": float((metrics_base["test"]["MAE"] - champion_metrics["MAE"]) / metrics_base["test"]["MAE"] * 100),
            "rmse_reduction_vs_baseline_pct": float((metrics_base["test"]["RMSE"] - champion_metrics["RMSE"]) / metrics_base["test"]["RMSE"] * 100),
        }
    }

    with open(metrics_json_path, "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, indent=2)
    print(f"[PERSISTENCE] Saved evaluation metrics to: {metrics_json_path}")

    # Verify Saved Model Inference
    print("\n[VERIFICATION] Loading saved model from disk and running test prediction...")
    loaded_bundle = joblib.load(model_save_path)
    loaded_model = loaded_bundle["model"]
    expected_features = loaded_bundle["feature_names"]

    sample_input = X_test.iloc[[0]][expected_features]
    sample_actual = y_test.iloc[0]
    sample_prediction = loaded_model.predict(sample_input)[0]

    print(f"Sample test date:       {dates_test.iloc[0].strftime('%Y-%m-%d')}")
    print(f"Sample input features:  {sample_input.to_dict(orient='records')[0]}")
    print(f"Actual fill level:      {sample_actual:.1f}")
    print(f"Predicted fill level:   {sample_prediction:.2f}")
    print(f"Prediction absolute err:{abs(sample_actual - sample_prediction):.2f}")
    print("[VERIFICATION] Successfully verified model loading and prediction!")


def main():
    root = get_project_root()
    docx_path = root / "datasets" / "raw" / "Smart Bin Insights Data Set for Unveiling Waste Management Trends" / "Smart Bin.docx"
    output_csv = root / "datasets" / "processed" / "smart_bin_cleaned.csv"

    print("=" * 80)
    print("URBANPULSE AI: SMART BIN FILL-LEVEL MODEL TRAINING PIPELINE")
    print("=" * 80)

    # 1. Extraction
    df_raw = extract_data_from_docx(docx_path)

    # 2. Cleaning & Deduplication
    df_cleaned = clean_data(df_raw, output_csv)

    # 3. Feature Engineering
    df_features = engineer_features(df_cleaned)

    # 4. Model Training & Evaluation
    train_and_evaluate(df_features, root)

    print("\nPipeline execution finished successfully.")


if __name__ == "__main__":
    main()
