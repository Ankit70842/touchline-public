import unittest
import tempfile
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from touchline.valuation import (attach_previous_valuations, build_history_snapshots,
                                chronological_split, fit_update, predict_update)
from touchline.features import build_snapshots, FEATURES
from touchline.evaluate import grouped_metrics, calibration_radius, run_experiment


class DatedValuationTests(unittest.TestCase):
    def test_target_and_future_prices_cannot_change_prior_features_even_if_conflicting(self):
        targets = pd.DataFrame([{'player_id': 1, 'date': '2024-06-01'}])
        history = {'1': [{'date': '2024-05-01', 'market_value_in_eur': 100},
                         {'date': '2024-06-01', 'market_value_in_eur': 999},
                         {'date': '2024-06-01', 'market_value_in_eur': 888},
                         {'date': '2025-01-01', 'market_value_in_eur': 777}]}
        row = attach_previous_valuations(targets, history).iloc[0]
        self.assertEqual(row.previous_value, 100)

    def test_complete_experiment_does_not_select_or_calibrate_on_test_targets(self):
        # Small artificial fixtures exercise the public pipeline, not football evidence.
        history = {'1': [{'date': f'{year}-06-01', 'market_value_in_eur': (year-2010)*1000000}
                         for year in range(2016, 2027)]}
        player = dict(player_id=1, name='Fixture', date='2026-06-01', actual_value=16000000,
            age=25, position='Attack', league='GB1', minutes=900, appearances=10, goals=2,
            assists=1, goals_per90=.2, assists_per90=.1, yellow_cards=0, red_cards=0,
            recent_minutes=90, recent_goals=0, recent_assists=0)
        stats = DummyRegressor(strategy='constant', constant=np.log1p(1000000))
        stats.fit(pd.DataFrame([player])[FEATURES], [np.log1p(1000000)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            joblib.dump({'model': stats, 'radius': .5}, path/'model.joblib')
            (path/'history.json').write_text(json.dumps(history))
            (path/'players.json').write_text(json.dumps([player]))
            first = run_experiment(path)
            history['1'][-1]['market_value_in_eur'] = 900000000
            player['actual_value'] = 900000000
            (path/'history.json').write_text(json.dumps(history))
            (path/'players.json').write_text(json.dumps([player]))
            changed = run_experiment(path)
            self.assertEqual(first['selection'], changed['selection'])
            self.assertEqual(first['interval']['log_radius'], changed['interval']['log_radius'])
            self.assertNotEqual(first['results']['previous_value'], changed['results']['previous_value'])

    def test_grouped_evaluation_and_separate_calibration(self):
        report = grouped_metrics([40_000_000, 60_000_000, 120_000_000],
                                 [30_000_000, 50_000_000, 100_000_000])
        self.assertEqual(report['above_50m']['rows'], 2)
        self.assertEqual(report['above_50m']['mae_eur'], 15_000_000)
        self.assertEqual(report['above_100m']['rows'], 1)
        self.assertEqual(report['above_100m']['mae_eur'], 20_000_000)
        self.assertEqual(calibration_radius([100, 200, 300], [100, 200, 300]), 0)

    def test_persistence_prediction_uses_stats_fallback_without_history(self):
        rows = pd.DataFrame([
            {'previous_value': 100, 'previous_value_age_days': 31, 'actual_value': 110},
            {'previous_value': None, 'previous_value_age_days': None, 'actual_value': 80}])
        model = fit_update('previous_value', rows)
        predicted, fallback = predict_update(model, rows, [500, 80])
        self.assertAlmostEqual(predicted[0], 100)
        self.assertAlmostEqual(predicted[1], 80)
        self.assertEqual(fallback.tolist(), [False, True])

    def test_annual_history_and_four_disjoint_chronological_partitions(self):
        history = {'7': [{'date': d, 'market_value_in_eur': v} for d, v in [
            ('2022-01-01', 10), ('2023-06-01', 20), ('2023-12-01', 30),
            ('2024-06-01', 40), ('2025-06-01', 50), ('2026-06-01', 60)]]}
        rows = build_history_snapshots(history)
        parts = chronological_split(rows, 2026)
        self.assertEqual([len(parts[k]) for k in ['train', 'validation', 'calibration', 'test']], [2, 1, 1, 1])
        self.assertEqual(parts['train'].iloc[-1].actual_value, 30)
        self.assertEqual(parts['validation'].iloc[0].previous_value, 30)
        dates = [set(p.date) for p in parts.values()]
        self.assertEqual(sum(map(len, dates)), len(set.union(*dates)))

    def test_snapshot_retains_pre_2015_history_and_excludes_target_day_matches(self):
        players = pd.DataFrame([{'player_id': 1, 'name': 'Fixture',
                                 'date_of_birth': '1990-01-01', 'position': 'Attack'}])
        matches = pd.DataFrame([
            {'player_id': 1, 'date': d, 'minutes_played': 180, 'goals': g,
             'assists': 0, 'yellow_cards': 0, 'red_cards': 0,
             'competition_id': 'GB1', 'player_club_id': 10}
            for d, g in [('2015-01-01', 1), ('2015-01-10', 99)]])
        values = pd.DataFrame([
            {'player_id': 1, 'date': '2014-12-01', 'market_value_in_eur': 100},
            {'player_id': 1, 'date': '2015-01-10', 'market_value_in_eur': 200}])
        row = build_snapshots(players, matches, values).iloc[0]
        self.assertEqual(row.previous_value, 100)
        self.assertEqual(row.previous_value_date, '2014-12-01')
        self.assertEqual(row.goals, 1)
        self.assertEqual(row.stats_through, '2015-01-01')

    def test_uses_only_latest_strictly_earlier_price_and_keeps_missing_history(self):
        targets = pd.DataFrame([
            {'player_id': 1, 'date': '2024-06-01', 'actual_value': 999},
            {'player_id': 2, 'date': '2024-06-01', 'actual_value': 888}])
        history = {'1': [
            {'date': '2024-06-02', 'market_value_in_eur': 900},
            {'date': '2024-05-01', 'market_value_in_eur': 100},
            {'date': '2024-06-01', 'market_value_in_eur': 999},
            {'date': '2024-01-01', 'market_value_in_eur': 50}]}
        rows = attach_previous_valuations(targets, history)
        self.assertEqual(rows.iloc[0].previous_value, 100)
        self.assertEqual(rows.iloc[0].previous_value_date, '2024-05-01')
        self.assertEqual(rows.iloc[0].previous_value_age_days, 31)
        self.assertTrue(pd.isna(rows.iloc[1].previous_value))


if __name__ == '__main__':
    unittest.main()
