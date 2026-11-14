import unittest
from fastapi.testclient import TestClient
from touchline.api import app


class PitchApiStatusTests(unittest.TestCase):
    def test_small_arsenal_source_export_is_separate_from_training_claims(self):
        result = TestClient(app).get('/api/sources/pitchapi/arsenal')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['status'],'not_distributed')
        self.assertNotIn('source_rows',result.json())

    def test_offline_quality_audit_is_separate_from_collection_status(self):
        client = TestClient(app)
        result = client.get('/api/sources/pitchapi/quality')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['network_requests_this_audit'],0)
        self.assertFalse(result.json()['ready_for_training'])
        queue = client.get('/api/sources/pitchapi/review-queue').json()
        self.assertEqual(queue,[])

    def test_pilot_audit_is_readable_without_changing_prediction_source(self):
        client = TestClient(app)
        response = client.get('/api/sources/pitchapi')
        self.assertEqual(response.status_code,200)
        status = response.json()
        self.assertEqual(status['pilot_league'],'Premier League')
        self.assertFalse(status['continuously_live'])
        self.assertFalse(status['estimate_source_changed'])
        self.assertFalse(status['other_leagues_enabled'])
        mappings = client.get('/api/sources/pitchapi/mappings',params={'status':'needs_review'})
        self.assertEqual(mappings.status_code,200)
        self.assertTrue(all(m['status']=='needs_review' for m in mappings.json()))
        self.assertEqual(client.get('/api/sources/pitchapi/mappings?status=invalid').status_code,422)
        self.assertEqual(client.get('/api/metadata').json()['pitchapi_pilot'],status)


if __name__ == '__main__':
    unittest.main()
