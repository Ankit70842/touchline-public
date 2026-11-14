"""Dated price history features; target values never enter the feature matrix."""
from bisect import bisect_left
from datetime import date
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

UPDATE_FEATURES = ['log_previous_value', 'previous_value_age_days']


def attach_previous_valuations(targets, histories):
    rows = []
    for target in targets.to_dict('records'):
        target_date = date.fromisoformat(str(target['date']))
        # Conflicting same-day prices have no intraday ordering: reject them.
        by_date = {}
        for item in histories.get(str(target['player_id']), []):
            day = date.fromisoformat(str(item['date']))
            if day >= target_date:
                continue
            value = float(item['market_value_in_eur'])
            if not np.isfinite(value) or value <= 0:
                continue
            if day in by_date and by_date[day] != value:
                raise ValueError('Conflicting valuations on the same date')
            by_date[day] = value
        days = sorted(by_date)
        index = bisect_left(days, target_date) - 1
        previous_day = days[index] if index >= 0 else None
        target.update(previous_value=by_date[previous_day] if previous_day else None,
                      previous_value_date=previous_day.isoformat() if previous_day else None,
                      previous_value_age_days=(target_date-previous_day).days if previous_day else None)
        rows.append(target)
    return pd.DataFrame(rows)


def build_history_snapshots(histories):
    """One last dated valuation per player/year; no invented performance inputs."""
    records = [{'player_id': int(pid), 'date': item['date'],
                'actual_value': item['market_value_in_eur']}
               for pid, history in histories.items() for item in history
               if item['market_value_in_eur'] > 0]
    frame = pd.DataFrame(records).sort_values(['date', 'player_id'])
    frame['year'] = pd.to_datetime(frame.date).dt.year
    frame = frame.groupby(['player_id', 'year']).tail(1)
    return attach_previous_valuations(frame, histories).sort_values(['date', 'player_id']).reset_index(drop=True)


def chronological_split(rows, test_year):
    """Validation precedes separate calibration and untouched latest-year test."""
    year = pd.to_datetime(rows.date).dt.year
    masks = {'train': year < test_year-2, 'validation': year == test_year-2,
             'calibration': year == test_year-1, 'test': year == test_year}
    parts = {name: rows.loc[mask].copy() for name, mask in masks.items()}
    if any(part.empty for part in parts.values()):
        raise ValueError('Need nonempty training, validation, calibration and test periods')
    if (year > test_year).any():
        raise ValueError('Rows after the declared test period are not allowed')
    return parts


def update_matrix(rows):
    return pd.DataFrame({'log_previous_value': np.log1p(rows.previous_value),
                         'previous_value_age_days': rows.previous_value_age_days})[UPDATE_FEATURES]


def fit_update(name, rows):
    """Fit a bounded candidate using strictly dated history features only."""
    eligible = rows[rows.previous_value.notna()]
    if name == 'previous_value':
        return {'name': name, 'estimator': None}
    if eligible.empty:
        raise ValueError('Training an update requires prior valuations')
    if name == 'ridge_update':
        estimator = make_pipeline(StandardScaler(), Ridge(alpha=100))
    elif name == 'tree_update':
        estimator = HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=7,
            min_samples_leaf=40, l2_regularization=10, learning_rate=.05,
            early_stopping=False, random_state=42)
    else:
        raise ValueError('Unknown update model')
    residual = np.log1p(eligible.actual_value) - np.log1p(eligible.previous_value)
    estimator.fit(update_matrix(eligible), residual)
    return {'name': name, 'estimator': estimator}


def predict_update(bundle, rows, stats_predictions):
    """Price update with an explicit frozen performance-model fallback."""
    fallback = rows.previous_value.isna().to_numpy()
    result = np.asarray(stats_predictions, dtype=float).copy()
    eligible = rows.loc[~fallback]
    if not eligible.empty:
        if (eligible.previous_value <= 0).any() or (eligible.previous_value_age_days <= 0).any() or eligible.previous_value_age_days.isna().any():
            raise ValueError('Prior value must be positive and strictly earlier than prediction')
        logs = np.log1p(eligible.previous_value.to_numpy())
        if bundle['estimator'] is not None:
            logs = logs + bundle['estimator'].predict(update_matrix(eligible))
        result[~fallback] = np.maximum(0, np.expm1(logs))
    return result, fallback
