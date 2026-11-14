import json
from pathlib import Path
import tempfile
import unittest
from touchline.pitchapi import PitchClient, write_json
from touchline.pitchapi_readiness import audit_cached


class OfflineReadinessTests(unittest.TestCase):
    def test_partial_cache_cannot_count_as_complete_and_collection_reports_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root/'artifacts/pitchapi/status.json'
            mappings = root/'artifacts/pitchapi/player_mappings.json'
            write_json(status,{'network_requests_this_run':9,'historical_rows':0})
            write_json(mappings,[{'sentinel':'preserve existing work'}])
            original = (status.read_bytes(),mappings.read_bytes())
            client = PitchClient(root/'data/pitchapi-cache',api_key='')
            match = {'id':'m_fixture','date':'2021-08-13','status':'finished',
                     'score_home':0,'score_away':0,'home_team':{'id':'h'},'away_team':{'id':'a'}}
            for suffix,body in [('',match),('/players',[]),('/events',{'events':[]}),('/lineups',{})]:
                client.seed('/v1/matches/m_fixture'+suffix,body,fetched_at='2026-11-13T00:00:00Z')
            path = client.cache_path('/v1/matches/m_fixture/players')
            envelope = json.loads(path.read_text())
            envelope['complete_response'] = False
            write_json(path,envelope)
            result = audit_cached(root)
            self.assertEqual(result['complete_sample_matches'],0)
            self.assertEqual(result['cache_errors'][0]['code'],'PARTIAL_RESPONSE_REJECTED')
            self.assertEqual(result['network_requests_this_audit'],0)
            self.assertEqual((status.read_bytes(),mappings.read_bytes()),original)


if __name__=='__main__':
    unittest.main()
