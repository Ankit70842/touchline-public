import unittest
from fastapi.testclient import TestClient
from touchline.api import app
from touchline.features import FEATURES


class ModelApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.player = cls.client.get('/api/players', params={'q': 'Demo Player 01'}).json()[0]
        cls.payload = {k: cls.player[k] for k in FEATURES if k not in {'goals_per90', 'assists_per90'}}
        cls.payload.update(stats_as_of=cls.player['date'], model='valuation_aware',
            previous_value=cls.player['previous_value'], previous_value_date=cls.player['previous_value_date'],
            stats_through=cls.player['stats_through'])

    def test_valuation_update_matches_report_and_names_its_method(self):
        response = self.client.post('/api/predict', json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['predicted_value'], self.player['valuation_aware_value'])
        self.assertEqual(result['model'], 'valuation_aware')
        self.assertEqual(result['method'], 'previous_value')
        self.assertEqual(result['previous_value_date'], self.player['previous_value_date'])

    def test_reject_recent_output_without_playing_time(self):
        response = self.client.post('/api/predict', json=self.payload | {'recent_minutes': 0, 'recent_goals': 1})
        self.assertEqual(response.status_code, 422)

    def test_reject_invalid_dates_pairs_models_and_target_value_inputs(self):
        cases = [
            {'previous_value_date': self.payload['stats_as_of']},
            {'previous_value_date': '2099-01-01'}, {'previous_value_date': None},
            {'previous_value': None}, {'previous_value': 0}, {'model': 'unknown'},
            {'actual_value': 200000000}, {'stats_through': self.payload['stats_as_of']},
            {'goals': 1, 'recent_goals': 2}, {'age': 'NaN'}]
        for changes in cases:
            with self.subTest(changes=changes):
                result = self.client.post('/api/predict', json=self.payload | changes)
                self.assertEqual(result.status_code, 422, result.text)

    def test_missing_history_uses_identical_stats_prediction_and_interval(self):
        payload = self.payload | {'previous_value': None, 'previous_value_date': None}
        update = self.client.post('/api/predict', json=payload).json()
        stats = self.client.post('/api/predict', json=payload | {'model': 'stats_only'}).json()
        self.assertEqual(update['method'], 'stats_only_fallback')
        for key in ['predicted_value', 'lower', 'upper']:
            self.assertEqual(update[key], stats[key])

    def test_model_metadata_and_export_predictions_agree(self):
        metadata = self.client.get('/api/metadata').json()
        models = self.client.get('/api/models').json()
        self.assertEqual(models['models'][1]['selected_method'], metadata['valuation_update']['selection']['selected'])
        players = self.client.get('/api/players').json()
        sample = players[::100] + [p for p in players if p['previous_value'] is None]
        for player in sample:
            payload = {k: player[k] for k in FEATURES if k not in {'goals_per90', 'assists_per90'}}
            payload.update(stats_as_of=player['date'], previous_value=player['previous_value'],
                           previous_value_date=player['previous_value_date'], stats_through=player['stats_through'])
            for model, prefix in [('stats_only', ''), ('valuation_aware', 'valuation_aware_')]:
                result = self.client.post('/api/predict', json=payload | {'model': model})
                self.assertEqual(result.status_code, 200, result.text)
                for actual, exported in [('predicted_value', prefix+'value' if prefix else 'predicted_value'),
                                         ('lower', prefix+'lower'), ('upper', prefix+'upper')]:
                    self.assertEqual(result.json()[actual], player[exported])



if __name__ == '__main__':
    unittest.main()
