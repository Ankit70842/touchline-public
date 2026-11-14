"""Offline, bounded history experiments. No downloads; no test-driven tuning."""
import hashlib
import json
import math
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from touchline.features import FEATURES
from touchline.valuation import (attach_previous_valuations, build_history_snapshots,
                                chronological_split, fit_update, predict_update, UPDATE_FEATURES)

ROOT = Path(__file__).resolve().parents[1]


def grouped_metrics(actual, predicted):
    actual, predicted = np.asarray(actual, float), np.maximum(0, np.asarray(predicted, float))
    result = {}
    for label, mask in [('all', np.ones(len(actual), bool)),
                        ('above_50m', actual > 50_000_000), ('above_100m', actual > 100_000_000)]:
        y, p = actual[mask], predicted[mask]
        result[label] = {'rows': len(y),
            'mae_eur': round(float(np.mean(np.abs(y-p)))) if len(y) else None,
            'rmsle': round(float(np.sqrt(np.mean((np.log1p(y)-np.log1p(p))**2))), 4) if len(y) else None}
    return result


def calibration_radius(actual, predicted):
    residual = np.abs(np.log1p(np.asarray(actual))-np.log1p(np.asarray(predicted)))
    if not len(residual):
        raise ValueError('Need a separate nonempty calibration sample')
    quantile = min(1, math.ceil((len(residual)+1)*.8)/len(residual))
    return float(np.quantile(residual, quantile, method='higher'))


def run_experiment(artifact_dir):
    artifact_dir = Path(artifact_dir)
    source_files = ['history.json', 'model.joblib']
    hashes = {name: hashlib.sha256((artifact_dir/name).read_bytes()).hexdigest() for name in source_files}
    history = json.loads((artifact_dir/'history.json').read_text(encoding='utf-8'))
    original = json.loads((artifact_dir/'players.json').read_text(encoding='utf-8'))
    stats_bundle = joblib.load(artifact_dir/'model.joblib')
    parts = chronological_split(build_history_snapshots(history), 2026)
    train, validation = parts['train'], parts['validation']
    train = train[train.previous_value.notna()]
    validation = validation[validation.previous_value.notna()]
    names = ['previous_value', 'ridge_update', 'tree_update']
    scores = {}
    for name in names:
        model = fit_update(name, train)
        prediction, _ = predict_update(model, validation, np.zeros(len(validation)))
        scores[name] = grouped_metrics(validation.actual_value, prediction)
    # This is the only selection criterion. Latest-year outcomes are not consulted.
    selected = min(names, key=lambda name: scores[name]['all']['mae_eur'])
    decision = {'selection_metric': '2024 validation MAE on matching prior-history rows',
                'candidates': scores, 'selected': selected, 'features': UPDATE_FEATURES,
                'scope': 'Price history only; historical performance inputs unavailable'}
    (artifact_dir/'selection.json').write_text(json.dumps(decision, indent=2)+'\n', encoding='utf-8')

    fit_rows = pd.concat([train, validation], ignore_index=True)
    calibration = parts['calibration'][parts['calibration'].previous_value.notna()]
    # Final fit, then separate calibration. Test is evaluated only after freezing selection.
    models, radii = {}, {}
    for name in names:
        models[name] = fit_update(name, fit_rows)
        prediction, _ = predict_update(models[name], calibration, np.zeros(len(calibration)))
        radii[name] = calibration_radius(calibration.actual_value, prediction)

    players = attach_previous_valuations(pd.DataFrame(original), history)
    stats = np.maximum(0, np.expm1(stats_bundle['model'].predict(players[FEATURES])))
    eligible = players.previous_value.notna().to_numpy()
    reports, predictions = {}, {}
    for name in names:
        predicted, fallback = predict_update(models[name], players, stats)
        predictions[name] = predicted
        reports[name] = {'all_players_with_stats_fallback': grouped_metrics(players.actual_value, predicted),
            'matched_history': grouped_metrics(players.actual_value[eligible], predicted[eligible])}
    reports['stats_only'] = {'all_players_with_stats_fallback': grouped_metrics(players.actual_value, stats),
        'matched_history': grouped_metrics(players.actual_value[eligible], stats[eligible])}
    selected_prediction = predictions[selected]
    lower = np.maximum(0, np.expm1(np.log1p(selected_prediction)-radii[selected]))
    upper = np.expm1(np.log1p(selected_prediction)+radii[selected])
    # No history-only calibration can calibrate the stats fallback. Retain its original interval.
    lower[~eligible] = np.maximum(0, np.expm1(np.log1p(stats[~eligible])-stats_bundle['radius']))
    upper[~eligible] = np.expm1(np.log1p(stats[~eligible])+stats_bundle['radius'])
    covered = (players.actual_value.to_numpy() >= lower) & (players.actual_value.to_numpy() <= upper)
    intervals = {'nominal_coverage': .8, 'log_radius': radii[selected],
        'calibration_rows': len(calibration), 'matched_test_coverage': float(covered[eligible].mean()),
        'all_test_coverage': float(covered.mean()),
        'fallback_note': 'Original stats-only interval; no separate missing-history calibration sample'}
    summary = {'scope': decision['scope'], 'selection': decision,
        'source_sha256': hashes,
        'partitions': {name: {'rows': len(rows), 'start': min(rows.date), 'end': max(rows.date)}
                       for name, rows in parts.items()},
        'final_fit_rows': len(fit_rows), 'test_rows': len(players),
        'history_test_rows': int(eligible.sum()), 'fallback_test_rows': int((~eligible).sum()),
        'results': reports, 'interval': intervals,
        'beats_previous_value_on_test_mae': reports[selected]['matched_history']['all']['mae_eur'] < reports['previous_value']['matched_history']['all']['mae_eur'],
        'limitations': [
            'Historical performance CSVs are absent; a joint price/performance update was not trained.',
            'History cohort contains players included in the 2026 app: survivor/selection bias.',
            'Validation uses 2024; calibration uses 2025; test uses 2026. Players recur across years.',
            'Prior price date is strictly before the target, but source publication timestamps are unavailable.',
            'No live source, contract, injury, reputation, xG or defensive statistics.',
            'History is truncated to ten years; first retained records may have missing earlier history.',
            'Elite groups are defined by held-out recorded values for reporting only, never for feature selection.'
        ]}
    players['predicted_value'] = np.rint(stats).astype(int)
    players['lower'] = np.rint(np.maximum(0, np.expm1(np.log1p(stats)-stats_bundle['radius']))).astype(int)
    players['upper'] = np.rint(np.expm1(np.log1p(stats)+stats_bundle['radius'])).astype(int)
    players['valuation_aware_value'] = np.rint(selected_prediction).astype(int)
    players['valuation_aware_lower'] = np.rint(lower).astype(int)
    players['valuation_aware_upper'] = np.rint(upper).astype(int)
    players['valuation_aware_method'] = np.where(eligible, selected, 'stats_only_fallback')
    summary['examples'] = players[players.name.isin(['Erling Haaland', 'Kylian Mbappé', 'Pedri', 'Jude Bellingham'])][
        ['name', 'date', 'actual_value', 'previous_value', 'previous_value_date', 'predicted_value', 'valuation_aware_value']].to_dict('records')
    # One predictor bundle drives both exports and the API.
    bundle = {'schema_version': 1, 'selected': models[selected], 'radius': radii[selected],
              'features': UPDATE_FEATURES, 'stats_model_sha256': hashes['model.joblib']}
    joblib.dump(bundle, artifact_dir/'update_model.joblib', compress=3)
    (artifact_dir/'players.json').write_text(players.to_json(orient='records', force_ascii=False), encoding='utf-8')
    (artifact_dir/'evaluation.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    summary = run_experiment(ROOT/'artifacts')
    print(json.dumps({'selection': summary['selection'], 'results': summary['results'],
                      'interval': summary['interval'], 'examples': summary['examples']}, indent=2, ensure_ascii=False))
