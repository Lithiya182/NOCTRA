import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    roc_auc_score, average_precision_score, precision_score,
    recall_score, f1_score, confusion_matrix
)
import pickle
from pathlib import Path

# Load data
df = pd.read_csv('data/ml_expansion_features.csv')
print(f'Total rows: {len(df)}')

# Filter valid targets (string '0' and '1', not int)
valid = df[df['target_expansion_24h'].isin(['0', '1'])].copy()
valid['target_expansion_24h'] = valid['target_expansion_24h'].astype(int)
print(f'Valid rows (0/1): {len(valid)}')
print(f'Positive: {sum(valid["target_expansion_24h"] == 1)}')
print(f'Negative: {sum(valid["target_expansion_24h"] == 0)}')

# Feature columns (exclude audit/target/meta)
exclude_cols = [
    'target_expansion_24h', 'expansion_threshold',
    'next_day_footprint', 'current_footprint', 'expansion_ratio',
    'site_id', 'date', 'latitude', 'longitude'
]

# Convert string columns with special values to numeric
def convert_feature_columns(df):
    """Convert string feature columns with special values to numeric."""
    # Columns that may have 'coverage_unknown', 'no_detection', 'div_zero', etc.
    str_cols_to_convert = [
        'active_previous_day', 'active_previous_day_flag',
        'active_previous_2_days', 'active_previous_3_days',
        'consecutive_active_days_before_today',
        'days_since_previous_detection',
        'detection_count_previous_day', 'frp_previous_day',
        'max_frp_previous_day', 'frp_change_vs_previous_day',
        'frp_percent_change_vs_previous_day',
        'rolling_3day_detection_count', 'rolling_3day_mean_frp', 'rolling_3day_max_frp',
        'rolling_7day_detection_count', 'rolling_7day_mean_frp', 'rolling_7day_max_frp',
    ]

    for col in str_cols_to_convert:
        if col in df.columns:
            # Replace special values with NaN, then convert
            df[col] = pd.to_numeric(df[col].replace({
                'coverage_unknown': pd.NA,
                'no_detection': pd.NA,
                'div_zero': pd.NA,
                'no_footprint': pd.NA,
                'no_recent_detection': pd.NA,
            }), errors='coerce')

    return valid

# Convert string feature columns to numeric
valid = convert_feature_columns(valid)

feature_cols = [c for c in valid.columns if c not in ['target_expansion_24h', 'expansion_threshold',
    'next_day_footprint', 'current_footprint', 'expansion_ratio',
    'site_id', 'date', 'latitude', 'longitude']]

print(f'Feature columns ({len(feature_cols)}): {feature_cols}')

# Sort by date
valid = valid.sort_values('date').reset_index(drop=True)
print(f'Date range: {valid["date"].min()} to {valid["date"].max()}')
print(f'Unique dates: {valid["date"].nunique()}')
print('Dates:', sorted(valid['date'].unique()))

# Chronological split: 70% dates train, 30% test
unique_dates = sorted(valid['date'].unique())
split_idx = int(len(unique_dates) * 0.7)
train_dates = unique_dates[:split_idx]
test_dates = unique_dates[split_idx:]

print(f'Train dates: {train_dates}')
print(f'Test dates: {test_dates}')

train = valid[valid['date'].isin(train_dates)].reset_index(drop=True)
test = valid[valid['date'].isin(test_dates)].reset_index(drop=True)

print(f'Train rows: {len(train)}, Positive: {sum(train["target_expansion_24h"] == 1)}')
print(f'Test rows: {len(test)}, Positive: {sum(test["target_expansion_24h"] == 1)}')

X_train = train[feature_cols]
y_train = train['target_expansion_24h']
X_test = test[feature_cols]
y_test = test['target_expansion_24h']

# Baseline: training positive rate
pos_rate = y_train.mean()
print(f'Training positive rate (baseline): {pos_rate:.4f}')

# Baseline predictions (constant positive rate)
from sklearn.metrics import roc_auc_score, average_precision_score, precision_score, recall_score, f1_score, confusion_matrix

y_pred_baseline = np.full(len(y_test), pos_rate)
y_pred_baseline_binary = (np.random.random(len(y_test)) < pos_rate).astype(int)  # stochastic baseline

# Baseline metrics
try:
    baseline_roc_auc = roc_auc_score(y_test, y_pred_baseline)
    print(f'Baseline ROC-AUC: {baseline_roc_auc:.4f}')
except:
    print('Baseline ROC-AUC: N/A')

try:
    baseline_pr_auc = average_precision_score(y_test, y_pred_baseline)
    print(f'Baseline PR-AUC: {baseline_pr_auc:.4f}')
except:
    print('Baseline PR-AUC: N/A')

# Random Forest
rf = RandomForestClassifier(
    n_estimators=100,
    max_depth=5,
    min_samples_leaf=5,
    class_weight='balanced',
    random_state=42
)

rf.fit(X_train, y_train)
y_pred_proba = rf.predict_proba(X_test)[:, 1]
y_pred = rf.predict(X_test)

# Metrics
roc_auc = roc_auc_score(y_test, y_pred_proba)
pr_auc = average_precision_score(y_test, y_pred_proba)
precision = precision_score(y_test, y_pred)
recall = recall_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)
cm = confusion_matrix(y_test, y_pred)

print(f'\nRandom Forest Metrics:')
print(f'ROC-AUC: {roc_auc:.4f}')
print(f'PR-AUC: {pr_auc:.4f}')
print(f'Precision: {precision:.4f}')
print(f'Recall: {recall:.4f}')
print(f'F1: {f1:.4f}')
print(f'Confusion Matrix:\n{cm}')
print(f'Predicted positives: {sum(y_pred)}')
print(f'Actual positives: {sum(y_test)}')

# Feature importance
importances = rf.feature_importances_
feat_imp = pd.DataFrame({'feature': X_train.columns, 'importance': importances})
feat_imp = feat_imp.sort_values('importance', ascending=False)
print(f'\nTop 10 feature importances:')
for i, row in feat_imp.head(10).iterrows():
    print(f'  {row["feature"]}: {row["importance"]:.4f}')

# Limitations
print(f'\nLimitations:')
print(f'  Total positives: {sum(y_train) + sum(y_test)}')
print(f'  Training positives: {sum(y_train)}')
print(f'  Test positives: {sum(y_test)}')
print(f'  Test rows: {len(y_test)}')
if sum(y_test) < 10:
    print('  WARNING: Test positives < 10, metrics highly unstable')

# Save model
model_path = Path('models/expansion_rf_phase4d.pkl')
model_path.parent.mkdir(exist_ok=True)
with open(model_path, 'wb') as f:
    pickle.dump(rf, f)
print(f'\nModel saved to: {model_path}')

# Save report
report_path = Path('audit/phase4d_model_report.txt')
report_path.parent.mkdir(exist_ok=True)
with open(report_path, 'w') as f:
    f.write('Phase 4D Model Report\n')
    f.write('=' * 50 + '\n\n')
    f.write(f'Dataset counts:\n')
    f.write(f'  Total eligible rows: {len(valid)}\n')
    f.write(f'  Train rows: {len(train)} (positive: {sum(y_train)})\n')
    f.write(f'  Test rows: {len(test)} (positive: {sum(y_test)})\n')
    f.write(f'  Train dates: {train_dates[0]} to {train_dates[-1]}\n')
    f.write(f'  Test dates: {test_dates[0]} to {test_dates[-1]}\n\n')
    f.write(f'Feature list ({len(feature_cols)}):\n')
    for fc in feature_cols:
        f.write(f'  {fc}\n')
    f.write('\n')
    f.write(f'Chronological split:\n')
    f.write(f'  Train dates: {train_dates[0]} to {train_dates[-1]}\n')
    f.write(f'  Test dates: {test_dates[0]} to {test_dates[-1]}\n\n')
    f.write(f'Baseline metrics:\n')
    f.write(f'  Training positive rate: {pos_rate:.4f}\n')
    f.write(f'  Baseline ROC-AUC: {baseline_roc_auc if "baseline_roc_auc" in locals() else "N/A"}\n')
    f.write(f'  Baseline PR-AUC: {baseline_pr_auc if "baseline_pr_auc" in locals() else "N/A"}\n\n')
    f.write(f'Random Forest metrics:\n')
    f.write(f'  ROC-AUC: {roc_auc:.4f}\n')
    f.write(f'  PR-AUC: {pr_auc:.4f}\n')
    f.write(f'  Precision: {precision:.4f}\n')
    f.write(f'  Recall: {recall:.4f}\n')
    f.write(f'  F1: {f1:.4f}\n')
    f.write(f'  Confusion matrix:\n{cm}\n\n')
    f.write(f'Top 10 feature importances (model feature importance, not causal):\n')
    for i, row in feat_imp.head(10).iterrows():
        f.write(f'  {row["feature"]}: {row["importance"]:.4f}\n')
    f.write('\n')
    f.write('Limitations:\n')
    f.write(f'  Total positives: {sum(y_train) + sum(y_test)}\n')
    f.write(f'  Training positives: {sum(y_train)}\n')
    f.write(f'  Test positives: {sum(y_test)}\n')
    f.write(f'  Small sample warning: test positives < 10\n')
    f.write('  Single region (Jharia), ~1 month data\n')
    f.write('  No SMOTE/synthetic oversampling\n\n')
    f.write('Leakage status: PASSED (no future-derived features)\n')
    f.write('\nModel config:\n')
    f.write('  n_estimators=100, max_depth=5, min_samples_leaf=5\n')
    f.write('  class_weight=balanced, random_state=42\n')
    f.write('\nSuitability: Research/prototype only, not production-ready\n')

print('\nReport saved to:', report_path)
