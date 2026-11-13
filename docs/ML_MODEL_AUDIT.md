# UrbanPulse AI — Smart Bin Fill-Level Prediction
## Technical Machine Learning Model & Pipeline Audit Report

**Author:** Senior Machine Learning Engineer  
**Audit Target:** Fill-Level Prediction Pipeline, Champion Model & Inference Service  
**Artifacts Audited & Updated:**
- `datasets/processed/smart_bin_cleaned.csv`
- `ml/src/train_pipeline.py`
- `ml/src/inference.py` *(New Inference Wrapper)*
- `tests/test_inference.py` *(New Automated Test Suite)*
- `ml/notebooks/02_train_fill_level_model.ipynb`
- `ml/models/smart_bin_fill_predictor.joblib`
- `ml/evaluation/model_metrics.json`
- `ml/evaluation/plots/`

**Audit Date:** November 2026  
**Status:** Audit Verified & Corrected — Inference Wrapper Implemented  

---

## Executive Summary

A comprehensive technical audit of the **UrbanPulse AI Smart Bin Fill-Level Prediction** model pipeline was conducted to evaluate data continuity, feature leakage, temporal train-test partitioning, metrics reproducibility, and inference validity.

### Key Audit Findings & Corrections:
1. **Date Continuity & Transition Denominator Correction**:
   - The dataset spans **736 calendar days** (`2018-06-25` to `2020-06-29`) and contains **659 recorded observations**.
   - These 659 sequential observations define exactly **658 consecutive transitions (intervals)** ($N - 1 = 658$).
   - **Correction**: The initial audit draft inadvertently used the observation count (659) as the percentage denominator. Using the mathematically correct denominator of 658 intervals:
     - Regular daily transitions ($\Delta t = 1.0 days$): **646 out of 658 (98.1763%)**.
     - Irregular transitions ($\Delta t > 1.0 days$): **12 out of 658 (1.8237%)**.
     - Missing calendar days: **77 days** (10.46% of calendar days missing).
2. **Feature Definition (`lag_1`)**:
   - Because feature engineering was performed on consecutive rows without daily grid resampling, `lag_1` strictly represents the **previous available observation**, not necessarily the previous calendar day.
3. **Data Leakage & Splitting**:
   - **Zero target leakage detected**. Train and test sets were split strictly chronologically ($80/20$), ensuring past observations are never predicted using future data.
4. **Metrics Reproducibility**:
   - Metrics recorded in `ml/evaluation/model_metrics.json` (MAE: 1.3166, RMSE: 1.6212, $R^2$: 0.4878) were **100% independently reproduced**.
5. **Inference Bounds Vulnerability & Implemented Solution**:
   - Out of 131 test set predictions, **10 predictions produced negative values** (minimum: **-0.7755**). In all 10 cases, the ground truth was `0.0` (bin emptying event).
   - An inference wrapper [`ml/src/inference.py`](file:///c:/Users/shiva/UrbanPulse-AI/ml/src/inference.py) was created. It applies domain-aware clipping to $[0.0, 10.0]$ while preserving unclipped raw predictions for auditing.
   - Bounded predictions improve test performance: MAE improves to **1.2975**, RMSE to **1.6185**, and $R^2$ to **0.4895**.
6. **Time-Gap Feature Investigation (`elapsed_days`)**:
   - Investigated the impact of adding `elapsed_days_since_previous_observation`.
   - In the training set, 11 transitions have $\Delta t > 1$; in the test set, only 1 transition has $\Delta t > 1$.
   - While adding `elapsed_days` provides a marginal empirical improvement (MAE: $1.3166 
ightarrow 1.3142$, $R^2$: $0.4878 
ightarrow 0.4924$), retraining was intentionally deferred because 12 total instances pose a high risk of memorizing specific historical downtime episodes rather than generalizable patterns.

---

## 1. Date Continuity & Time Grid Audit (Corrected)

### Observation Metrics:
- **Earliest Timestamp:** `2018-06-25 12:00:00`
- **Latest Timestamp:** `2020-06-29 12:00:00`
- **Total Calendar Span:** **736 calendar days**
- **Recorded Unique Observations ($N$):** **659 days**
- **Total Consecutive Transitions ($N - 1$):** **658 intervals**
- **Missing Calendar Days:** **77 days** ($736 - 659 = 77$, or **10.46%**)

### Consecutive Observation Time Gaps:
- **Minimum Gap:** `1.0 day` (24.0 hours)
- **Maximum Gap:** `21.0 days` (between `2019-01-30` and `2019-02-20`)
- **Median Gap:** `1.0 day`
- **Mean Gap:** `1.1170 days`

### Corrected Distribution of Time Gaps:
*Note: In any ordered sequence of $N = 659$ observations, the first observation has no preceding observation, yielding exactly $N - 1 = 658$ transition intervals. Percentages below use the correct denominator 658.*

| Time Gap ($\Delta t$) | Occurrences | Percentage (Denominator = 658) | Operational Significance |
| :---: | :---: | :---: | :--- |
| **1.0 day** | 646 | **98.1763%** | Regular daily cadence |
| **2.0 days** | 4 | **0.6079%** | Single missing day |
| **3.0 days** | 1 | **0.1520%** | Weekend or missing sensor report |
| **6.0 days** | 2 | **0.3040%** | Multi-day outage |
| **8.0 days** | 1 | **0.1520%** | Multi-day outage |
| **9.0 days** | 1 | **0.1520%** | Multi-day outage |
| **14.0 days** | 2 | **0.3040%** | Two-week sensor downtime |
| **21.0 days** | 1 | **0.1520%** | Three-week sensor downtime (`2019-01-30` to `2019-02-20`) |
| **Total Intervals** | **658** | **100.0000%** | **646 Regular (98.18%) + 12 Irregular (1.82%)** |

### Critical Finding: What Does `lag_1` Represent?
- **Finding:** `lag_1 = df['latestFullness'].shift(1)` is a row-level shift. Consequently, `lag_1` represents the **previous available observation**, **NOT the previous calendar day**.
- **Evidence:**
  - On `2018-11-22` (row 137), the gap from the prior row was **14 days**. `lag_1` took the value from `2018-11-08`.
  - On `2019-02-20` (row 175), the gap was **21 days**. `lag_1` took the value from `2019-01-30`.
- **Engineering Assessment:**
  For 98.18% of the transitions, row $i-1$ is identical to calendar day $t-1$. However, in the 12 irregular transitions, the model receives stale information from days or weeks prior while treating it as yesterday's reading.

---

## 2. Feature Engineering & Leakage Audit

### 1. Lag Feature Inspection:
- Features: `lag_1 = y.shift(1)`, `lag_2 = y.shift(2)`, `lag_3 = y.shift(3)`, `lag_7 = y.shift(7)`
- **Audit Result:** Clean. No target value from day $t$ or later is ever present in lag columns.

### 2. Rolling Feature Inspection:
- Features:
  - `rolling_mean_3 = y.shift(1).rolling(window=3).mean()`
  - `rolling_mean_7 = y.shift(1).rolling(window=7).mean()`
- **Audit Result:** Clean. Because the series is explicitly shifted by 1 before applying the rolling window, the rolling average for observation $i$ covers exactly $[i-3, i-1]$ (for window 3) and $[i-7, i-1]$ (for window 7). Target $y_i$ is completely excluded from the rolling window.
- **Target Leakage Check:** Zero leakage.

### 3. Calendar Feature Inspection:
- Features: `day_of_week` (`dt.dayofweek`) and `month` (`dt.month`).
- **Audit Result:** Clean. These features are deterministic properties of the forecast timestamp itself and are legitimately known at prediction time.

---

## 3. Data Splitting & Temporal Integrity Audit

### 1. Splitting Strategy:
- **Method:** Chronological 80/20 train-test partition.
- **Training Subset:** 521 observations (`2018-07-02 12:00:00` to `2020-02-18 12:00:00`).
- **Testing Subset:** 131 observations (`2020-02-19 12:00:00` to `2020-06-29 12:00:00`).

### 2. Future Information Audit:
- Maximum date in training set: `2020-02-18 12:00:00`
- Minimum date in testing set:  `2020-02-19 12:00:00`
- Condition: $\max({train}) < \min({test})$ is **strictly True**. Zero future leakage.

### 3. Historical Transition for Test Samples:
- The first test sample (`2020-02-19`, row 521) uses `lag_1 = 6.0` (from row 520, `2020-02-18` in the training set).
- **Audit Result:** Legitimate. In real-world time-series forecasting, forecasting day $T+1$ requires the sensor telemetry recorded on day $T$. Test feature generation legitimately references historical training values without leaking test target labels into model fitting.

---

## 4. Model Validation & Reproducibility Audit

### 1. Independent Metric Re-computation:
The model bundle `ml/models/smart_bin_fill_predictor.joblib` was loaded and evaluated on the exact test set.

| Metric | Independently Computed | Stored in `model_metrics.json` | Discrepancy | Verification Status |
| :--- | :---: | :---: | :---: | :---: |
| **Test MAE** | `1.316629` | `1.316629` | `0.000000` | **Verified Match** |
| **Test RMSE** | `1.621220` | `1.621220` | `0.000000` | **Verified Match** |
| **Test $R^2$** | `0.487767` | `0.487767` | `0.000000` | **Verified Match** |

### 2. Comparison Against Persistence Baseline:
| Model | Test MAE | Test RMSE | Test $R^2$ | Error Reduction vs Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Persistence Baseline** | 1.7863 | 2.9187 | -0.6603 | Baseline |
| **Random Forest Regressor** | 1.3438 | 1.6906 | 0.4430 | MAE: -24.77%, RMSE: -42.08% |
| **HistGradientBoosting Regressor** | **1.3166** | **1.6212** | **0.4878** | **MAE: -26.29%, RMSE: -44.46%** |

---

## 5. Inference Range & Boundary Value Audit

### 1. Test Set Prediction Range:
- **Minimum Raw Prediction:** **-0.7755**
- **Maximum Raw Prediction:** **6.2453**
- **Predictions Outside $[0.0, 10.0]$:** **10 out of 131 test samples (7.63%)**.

### 2. Analysis of Negative Predictions:
All 10 instances of negative predictions occurred on days where the actual fill level was **`0.0`**:

| Index | Date | Actual Fill | Raw Model Prediction | Bounded Prediction | `lag_1` | `rolling_mean_3` |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **525** | 2020-02-23 | 0.0 | **-0.0862** | **0.0000** | 0.0 | 4.00 |
| **567** | 2020-04-05 | 0.0 | **-0.6020** | **0.0000** | 6.0 | 4.67 |
| **568** | 2020-04-06 | 0.0 | **-0.1948** | **0.0000** | 0.0 | 3.33 |
| **581** | 2020-04-19 | 0.0 | **-0.7755** | **0.0000** | 6.0 | 4.67 |
| **582** | 2020-04-20 | 0.0 | **-0.0657** | **0.0000** | 0.0 | 3.33 |
| **603** | 2020-05-12 | 0.0 | **-0.1631** | **0.0000** | 6.0 | 4.67 |
| **633** | 2020-06-11 | 0.0 | **-0.0795** | **0.0000** | 6.0 | 4.67 |
| **646** | 2020-06-24 | 0.0 | **-0.2244** | **0.0000** | 8.0 | 4.33 |
| **650** | 2020-06-28 | 0.0 | **-0.2490** | **0.0000** | 6.0 | 3.33 |
| **651** | 2020-06-29 | 0.0 | **-0.0679** | **0.0000** | 0.0 | 3.33 |

### 3. Root Cause:
`HistGradientBoostingRegressor` is an additive tree regressor optimizing unconstrained Mean Squared Error loss. When predicting bin-emptying cycles, tree leaf outputs sum to small negative values (down to -0.78).

### 4. Implemented Solution: `SmartBinPredictor` Inference Wrapper
The wrapper in `ml/src/inference.py` decouples physical boundary enforcement from model serialization:
```python
raw_prediction = float(self.model.predict(input_df)[0])
bounded_prediction = float(np.clip(raw_prediction, 0.0, 10.0))
```
- Both `raw_prediction` and `bounded_prediction` are returned along with `was_clipped` and `clip_direction`.
- The original model file (`smart_bin_fill_predictor.joblib`) remains untouched.
- Evaluation metrics recorded in `model_metrics.json` reflect the official unclipped training state.

### 5. Metric Impact of Bounded Inference on Test Set:
| Metric | Raw Unclipped Predictions | Bounded Predictions $[0.0, 10.0]$ | Delta Improvement |
| :--- | :---: | :---: | :---: |
| **MAE** | 1.316629 | **1.297485** | **-0.019144 (-1.45%)** |
| **RMSE** | 1.621220 | **1.618479** | **-0.002741 (-0.17%)** |
| **$R^2$** | 0.487767 | **0.489498** | **+0.001731 (+0.35%)** |

---

## 6. Time-Gap Feature Investigation (`elapsed_days`)

### 1. Motivation:
Because 12 transitions span intervals greater than 1 day, adding an `elapsed_days_since_previous_observation` feature was investigated to determine whether explicitly providing the time delta helps the model discount stale historical lags.

### 2. Empirical Findings:
- **Sample Distribution**:
  - Training Set (521 rows): 11 instances with $\Delta t > 1$ (three 2-day, two 6-day, one 3-day, one 8-day, one 9-day, two 14-day, one 21-day).
  - Testing Set (131 rows): **Only 1 single instance** with $\Delta t > 1$ (one 2-day gap on `2020-05-06`).
- **Benchmark Comparison**:
  - Baseline (8 features): MAE = 1.316629, RMSE = 1.621220, $R^2$ = 0.487767
  - With `elapsed_days` (9 features): MAE = 1.314228, RMSE = 1.613869, $R^2$ = 0.492402

### 3. Technical Assessment & Recommendation:
- While the inclusion of `elapsed_days` yields a slight numerical gain on the test set ($\Delta R^2 pprox +0.0046$), **retraining is not recommended at this stage**:
  1. **Extreme Class Imbalance**: With only 11 training rows having $\Delta t > 1$, tree splits on `elapsed_days` risk overfitting to those 11 specific historical outage episodes.
  2. **Evaluation Blind Spot**: The test set contains only 1 gap instance, meaning test metrics cannot reliably prove that the model learned a generalizable decay dynamic.
  3. **Architectural Recommendation**: For the next dataset iteration (multi-bin municipal IoT), sample observations at regular intervals (e.g. hourly) and include an explicit missingness indicator flag (`is_interpolated: 0/1`) rather than training on irregular time steps.

---

## 7. Audit Summary Matrix

| Audit Dimension | Status | Key Finding | Action Taken / Recommendation |
| :--- | :---: | :--- | :--- |
| **Interval Denominator** | ✅ Corrected | 659 observations yield 658 transitions. | Corrected: 646 regular (98.18%) and 12 irregular (1.82%). |
| **Target Leakage** | ✅ Passed | Features strictly use historical data via shifted rolling windows. | Verified zero leakage. |
| **Data Splitting** | ✅ Passed | Chronological 80/20 partition; $\max({train}) < \min({test})$. | Verified temporal separation. |
| **Reproducibility** | ✅ Passed | Exactly matches `model_metrics.json`. | 100% verified. |
| **Inference Bounds** | ✅ Resolved | 10 test predictions were negative (min -0.7755) during emptying events. | Implemented `SmartBinPredictor` with $[0.0, 10.0]$ clipping and raw preservation. |
| **Time-Gap Awareness** | ℹ️ Analyzed | Adding `elapsed_days` yields marginal gain (+0.0046 $R^2$), but sample size (12 gaps) is too small. | Documented findings; deferred retraining to avoid overfitting on 11 training instances. |

### Operational Status:
The model pipeline is **fully verified as an experimental baseline**. The inference wrapper [`ml/src/inference.py`](file:///c:/Users/shiva/UrbanPulse-AI/ml/src/inference.py) provides a physically valid prediction interface ready for integration with the backend API.
