"""League-only historical rows, isolated from shipped all-competition models."""
from datetime import date, timedelta
import math
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from touchline.evaluate import calibration_radius, grouped_metrics
from touchline.valuation import chronological_split
from touchline.pitchapi import write_json

PILOT_FEATURES = ['minutes','appearances','goals','assists',
                  'xg','xa','recent_minutes','recent_goals','recent_assists']


def covered(start, end, coverage, player_id=None):
    cursor = start
    for item in sorted(coverage, key=lambda x:x['start']):
        if not item.get('complete') or item.get('league') != 'GB1':
            continue
        if item.get('player_ids') is not None and player_id not in item['player_ids']:
            continue
        left, right = date.fromisoformat(item['start']), date.fromisoformat(item['end_exclusive'])
        if left <= cursor < right:
            cursor = right
        if cursor >= end:
            return True
    return False


def total(rows, key):
    values = [row.get(key) for row in rows]
    if not values or any(v is None or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        return None
    return sum(values)


def build_pilot_rows(appearances, targets, mappings, coverage, *, cohort_player_ids=None):
    verified = {m['provider_player_id']:m['player_id'] for m in mappings
                if m.get('status') == 'verified' and m.get('evidence')}
    out_of_scope = {m['provider_player_id'] for m in mappings
                    if m.get('status') == 'out_of_scope' and m.get('evidence')}
    output, excluded = [], []
    for target in targets:
        if cohort_player_ids is not None and target['player_id'] not in cohort_player_ids:
            continue
        day = date.fromisoformat(target['date'])
        left, recent_left = day-timedelta(days=365), day-timedelta(days=90)
        reason = None
        if not covered(left, day, coverage, target['player_id']):
            reason = 'incomplete_365_day_collection_window'
        eligible = [a for a in appearances if left <= date.fromisoformat(a['date']) < day]
        if cohort_player_ids is not None:
            # Opponents and unselected teammates are not part of this supervised cohort.
            eligible = [a for a in eligible if verified.get(a['provider_player_id']) in cohort_player_ids]
            if target['player_id'] not in verified.values():
                reason = 'target_identity_not_verified'
        if any(a.get('participation') != 'unused_bench' and a['provider_player_id'] not in verified
               and a['provider_player_id'] not in out_of_scope for a in eligible):
            reason = 'unverified_identity_in_collection_window'
        matches = sorted([a for a in eligible if verified.get(a['provider_player_id']) == target['player_id']
                          and a.get('participation') != 'unused_bench'],key=lambda x:(x['date'],x['match_id']))
        if len({a['match_id'] for a in matches}) != len(matches):
            reason = 'duplicate_player_match_rows'
        if not matches or any(a.get('participation') != 'played' for a in matches):
            reason = reason or 'unresolved_participation_or_no_matches'
        minutes = total(matches, 'minutes')
        if minutes is None or minutes < 180:
            reason = reason or 'missing_or_insufficient_minutes'
        if reason:
            excluded.append({'player_id':target['player_id'],'date':target['date'],'reason':reason})
            continue
        recent = [a for a in matches if date.fromisoformat(a['date']) >= recent_left]
        row = {k:target[k] for k in ['player_id','date','actual_value']}
        row.update({k:total(matches,k) for k in ['minutes','goals','assists','xg','xa']})
        row.update(appearances=len(matches), league='GB1', stats_through=matches[-1]['date'],
            performance_window_start=left.isoformat(), source_match_ids=[a['match_id'] for a in matches],
            source_fetched_at=sorted({a['fetched_at'] for a in matches if a.get('fetched_at')}),
            recent_minutes=total(recent,'minutes'),recent_goals=total(recent,'goals'),recent_assists=total(recent,'assists'))
        # No observed matches in a verified complete 90-day window is a known zero.
        if not recent:
            row.update(recent_minutes=0,recent_goals=0,recent_assists=0)
        previous = target.get('previous_value')
        previous_date = target.get('previous_value_date')
        if previous is not None and previous_date and date.fromisoformat(previous_date) < day:
            row.update(previous_value=previous,previous_value_date=previous_date,
                       previous_value_age_days=(day-date.fromisoformat(previous_date)).days)
        else:
            row.update(previous_value=None,previous_value_date=None,previous_value_age_days=None)
        output.append(row)
    return {'rows':output,'excluded_targets':excluded,'excluded_features':['yellow_cards','red_cards'],
            'scope':'Premier League only; never feed these totals into the shipped all-competition model'}


def fit_pilot_models(rows):
    features = [f for f in PILOT_FEATURES if rows[f].notna().any()]
    if not features:
        raise ValueError('No observed performance features in training')
    def estimator():
        return make_pipeline(SimpleImputer(strategy='median', add_indicator=True),
            HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=7,
                l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=42))
    stats = estimator().fit(rows[features], np.log1p(rows.actual_value))
    prior = rows[rows.previous_value.notna()].copy()
    if prior.empty:
        raise ValueError('Need earlier prices to train valuation changes')
    prior['log_previous_value'] = np.log1p(prior.previous_value)
    change_features = features+['log_previous_value','previous_value_age_days']
    change = estimator().fit(prior[change_features], np.log1p(prior.actual_value)-np.log1p(prior.previous_value))
    return {'stats':stats,'change':change,'features':features,'change_features':change_features}


def predict_pilot(models, rows):
    frame = rows.copy()
    stats = np.maximum(0,np.expm1(models['stats'].predict(frame[models['features']])))
    eligible = frame.previous_value.notna().to_numpy()
    previous, change = stats.copy(), stats.copy()
    if eligible.any():
        prior = frame.loc[eligible].copy()
        prior['log_previous_value'] = np.log1p(prior.previous_value)
        previous[eligible] = prior.previous_value
        change[eligible] = np.maximum(0,np.expm1(prior.log_previous_value +
            models['change'].predict(prior[models['change_features']])))
    return {'stats_only':stats,'previous_value':previous,'valuation_change':change}


def evaluate_pilot(rows, readiness, output_dir, *, min_period_rows=100):
    """Separate experiment; never replaces the shipped predictor implicitly."""
    if readiness.get('ready_for_training') is not True:
        raise ValueError('Pilot identity, collection and card-audit gates have not passed')
    frame = pd.DataFrame(rows)
    parts = chronological_split(frame,2026)
    if any(len(p)<min_period_rows for p in parts.values()):
        raise ValueError('Insufficient rows in a chronological partition')
    output_dir = Path(output_dir)
    models = fit_pilot_models(parts['train'])
    validation = parts['validation']
    eligible = validation.previous_value.notna().to_numpy()
    if eligible.sum()<min_period_rows:
        raise ValueError('Insufficient matching validation rows')
    predictions = predict_pilot(models,validation)
    order = ['previous_value','stats_only','valuation_change']
    scores = {name:grouped_metrics(validation.actual_value[eligible],predictions[name][eligible]) for name in order}
    selected = min(order,key=lambda name:scores[name]['all']['mae_eur'])
    decision = {'selected':selected,'criterion':'2024 matching-row validation MAE; ties prefer persistence',
                'validation':scores,'test_year':2026}
    write_json(output_dir/'pilot_selection.json',decision)
    models = fit_pilot_models(pd.concat([parts['train'],validation],ignore_index=True))
    calibration = parts['calibration']
    calibration_predictions = predict_pilot(models,calibration)
    calibration_mask = calibration.previous_value.notna().to_numpy()
    if calibration_mask.sum()<min_period_rows:
        raise ValueError('Insufficient matching calibration rows')
    radius = calibration_radius(calibration.actual_value[calibration_mask],
                                calibration_predictions[selected][calibration_mask])
    # Selection and interval calibration are frozen before these test predictions.
    test = parts['test']
    test_mask = test.previous_value.notna().to_numpy()
    predictions = predict_pilot(models,test)
    results = {name:{'all_players':grouped_metrics(test.actual_value,pred),
        'matched_history':grouped_metrics(test.actual_value[test_mask],pred[test_mask])}
        for name,pred in predictions.items()}
    logs = np.log1p(predictions[selected][test_mask])
    coverage = float(np.mean((test.actual_value[test_mask]>=np.maximum(0,np.expm1(logs-radius))) &
                            (test.actual_value[test_mask]<=np.expm1(logs+radius)))) if test_mask.any() else None
    result = {'selection':decision,'interval':{'nominal_coverage':.8,'log_radius':radius},
        'matched_test_coverage':coverage,'results':results,
        'partitions':{k:len(v) for k,v in parts.items()},'features':models['features'],
        'scope':'New league-only stats model and price-change model, not the shipped all-competition model',
        'limitations':['Provider observation timestamps do not prove historical publication availability.',
                       'Fallback calibration is not separately established.',
                       'No other league is approved by this Premier League experiment.']}
    joblib.dump(models|{'selected':selected,'radius':radius},output_dir/'pilot_model.joblib',compress=3)
    write_json(output_dir/'pilot_evaluation.json',result)
    return result
