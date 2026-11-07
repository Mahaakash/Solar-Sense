"""
scripts/train_model.py
──────────────────────
Model training script for SolarSense solar power forecasting:
1. Loads processed training dataset (data/processed/training.parquet).
2. Performs chronological time-based split (2.5 years train, last 6 months test).
3. Trains an XGBoost regressor model.
4. Evaluates test set MAE, RMSE, and R2 against naive 24-hour persistence baseline.
5. Saves model bundle to backend/models/solar_xgb.joblib.
6. Exports evaluation plot (forecast_check.png) and feature importance (feature_importance.png).
"""

import sys
from pathlib import Path

# Ensure backend package can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from backend import config


def main() -> None:
    print("=" * 65)
    print("SolarSense — Solar Power Forecast Model Training")
    print("=" * 65)

    data_path = Path(config.TRAINING_DATA_PATH)
    if not data_path.exists():
        msg = f"Training data not found at {data_path}. Run scripts/make_training_data.py first."
        raise FileNotFoundError(msg)

    print(f"\n1. Loading dataset from {data_path}...")
    df = pd.read_parquet(data_path)
    print(f"   Loaded {len(df):,} rows from {df.index.min()} to {df.index.max()}.")

    # 2. Chronological Time-Based Split (Last 6 Months for Test)
    split_cutoff = df.index.max() - pd.DateOffset(months=config.MODEL_TEST_MONTHS)
    train_mask = df.index < split_cutoff
    test_mask = df.index >= split_cutoff

    feature_cols = [c for c in df.columns if c != "power_kw"]
    target_col = "power_kw"

    X_train = df.loc[train_mask, feature_cols]
    y_train = df.loc[train_mask, target_col]
    X_test = df.loc[test_mask, feature_cols]
    y_test = df.loc[test_mask, target_col]

    train_start, train_end = X_train.index.min().date(), X_train.index.max().date()
    test_start, test_end = X_test.index.min().date(), X_test.index.max().date()
    print(f"\n2. Time-based split at {split_cutoff.strftime('%Y-%m-%d')}:")
    print(f"   Train set: {len(X_train):,} samples ({train_start} to {train_end})")
    print(f"   Test set:  {len(X_test):,} samples ({test_start} to {test_end})")

    # 3. Train XGBoost Regressor
    print("\n3. Training XGBoost regressor...")
    model = xgb.XGBRegressor(
        n_estimators=config.XGB_N_ESTIMATORS,
        max_depth=config.XGB_MAX_DEPTH,
        learning_rate=config.XGB_LEARNING_RATE,
        subsample=config.XGB_SUBSAMPLE,
        colsample_bytree=config.XGB_COLSAMPLE_BYTREE,
        random_state=config.XGB_RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    print("   Training complete.")

    # 4. Predictions & Evaluation
    print("\n4. Evaluating test set predictions...")
    y_pred_raw = model.predict(X_test)
    # Nighttime physical enforcement (zero irradiance -> zero power)
    night_mask = X_test["irradiance"] <= 0.0
    y_pred = np.clip(y_pred_raw, 0.0, config.REFERENCE_PLANT_CAPACITY_KW)
    y_pred[night_mask] = 0.0

    mae_xgb = mean_absolute_error(y_test, y_pred)
    rmse_xgb = np.sqrt(mean_squared_error(y_test, y_pred))
    r2_xgb = r2_score(y_test, y_pred)

    # Naive Baseline: Generation at the same hour yesterday (24-hour lag)
    # Compute using full dataset so initial test hours have yesterday's values
    naive_series = df[target_col].shift(24).loc[test_mask]
    valid_naive = naive_series.notnull()

    mae_naive = mean_absolute_error(y_test[valid_naive], naive_series[valid_naive])
    rmse_naive = np.sqrt(mean_squared_error(y_test[valid_naive], naive_series[valid_naive]))
    r2_naive = r2_score(y_test[valid_naive], naive_series[valid_naive])

    print("\n" + "-" * 60)
    print("MODEL EVALUATION RESULTS (Test Set: Last 6 Months)")
    print("-" * 60)
    print(f"{'Metric':<18} | {'Naive Baseline (24h)':<22} | {'XGBoost Model':<15}")
    print("-" * 60)
    print(f"{'MAE (kW)':<18} | {mae_naive:<22.4f} | {mae_xgb:<15.4f}")
    print(f"{'RMSE (kW)':<18} | {rmse_naive:<22.4f} | {rmse_xgb:<15.4f}")
    print(f"{'R² Score':<18} | {r2_naive:<22.4f} | {r2_xgb:<15.4f}")
    print("-" * 60)

    # 5. Save Model Artifact
    model_output_path = Path(config.MODEL_PATH)
    model_output_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "feature_names": feature_cols,
        "reference_capacity_kw": config.REFERENCE_PLANT_CAPACITY_KW,
    }
    joblib.dump(bundle, model_output_path)
    file_size_kb = model_output_path.stat().st_size / 1024
    print(f"\n5. Saved model artifact to {model_output_path} ({file_size_kb:.1f} KB).")

    # 6. Generate Diagnostic Plots
    notebooks_dir = Path("notebooks")
    notebooks_dir.mkdir(parents=True, exist_ok=True)

    # Plot A: 7-Day Forecast Check (168 hours)
    plot_start = split_cutoff + pd.DateOffset(days=30)
    plot_end = plot_start + pd.DateOffset(days=7)
    sample_indices = np.where((y_test.index >= plot_start) & (y_test.index < plot_end))[0][:168]

    plt.figure(figsize=(14, 5))
    plt.plot(
        y_test.index[sample_indices],
        y_test.iloc[sample_indices].values,
        label="Actual (kW)",
        color="#2c3e50",
        linewidth=1.8,
    )
    plt.plot(
        y_test.index[sample_indices],
        y_pred[sample_indices],
        label="XGBoost Predicted (kW)",
        color="#e67e22",
        linewidth=1.8,
        linestyle="--",
    )
    plt.title("SolarSense Forecast Check: Predicted vs Actual Power (Sample 7-Day Window)")
    plt.xlabel("Datetime")
    plt.ylabel("Power Generation (kW)")
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(frameon=True)
    plt.tight_layout()
    check_plot_path = Path(config.PLOT_FORECAST_CHECK_PATH)
    plt.savefig(check_plot_path, dpi=120)
    plt.close()
    print(f"   Saved forecast check curve to {check_plot_path}")

    # Plot B: Feature Importance
    importances = model.feature_importances_
    sorted_idx = np.argsort(importances)

    plt.figure(figsize=(10, 6))
    plt.barh(np.array(feature_cols)[sorted_idx], importances[sorted_idx], color="#27ae60")
    plt.title("XGBoost Feature Importance (Gain / Weight)")
    plt.xlabel("Relative Importance")
    plt.tight_layout()
    feat_plot_path = Path(config.PLOT_FEATURE_IMPORTANCE_PATH)
    plt.savefig(feat_plot_path, dpi=120)
    plt.close()
    print(f"   Saved feature importance chart to {feat_plot_path}")

    print("\n" + "=" * 65)
    print("Training pipeline completed successfully.")
    print("=" * 65)


if __name__ == "__main__":
    main()
