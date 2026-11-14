import tempfile
import unittest
from pathlib import Path
import httpx
from touchline.pitchapi import PitchClient, write_json
from touchline.pitchapi_collect_arsenal import collect_arsenal


def setup_root(root):
    write_json(root/'artifacts/pitchapi/arsenal_cohort.json',{
        'club':'Arsenal','provider_team_id':'a','league_id':'l_one','season':'2021/2022',
        'cached_match_id':'m_old','quarantined_match_ids':['m_bad'],
        'fixtures':[['2021-08-13','Opponent','away']]})


class ArsenalCollectionTests(unittest.TestCase):
    def test_outer_pagination_and_http_date_retry_after_are_not_ignored(self):
        for headers,body,status in [({}, {'data':{},'pagination':{'next_cursor':'more'}},200),
            ({'Retry-After':'Sat, 01 Jan 2050 00:00:00 GMT'},{'error':{'code':'RATE_LIMIT_EXCEEDED'}},429)]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);setup_root(root)
                client=PitchClient(root/'data/pitchapi-cache',api_key='fixture-key',transport=httpx.MockTransport(
                    lambda request:httpx.Response(status,headers=headers,json=body)))
                result=collect_arsenal(root,online=True,client=client,wait=lambda seconds:self.fail('Unsafe retry'))
                self.assertEqual(result['requests_used'],1)
                self.assertNotEqual(result['status'],'responses_cached')
                if status==200:
                    self.assertEqual(result['issues'][0]['code'],'UNSUPPORTED_PAGINATION')

    def test_complete_listing_recalculates_only_required_bodies_and_resumes_from_cache(self):
        calls=[]
        match={'id':'m_one','date':'2021-08-13','status':'finished','score_home':0,'score_away':0,
               'home_team':{'id':'h','name':'Opponent'},'away_team':{'id':'a','name':'Arsenal'}}
        def endpoint(request):
            calls.append(request.url.path)
            if '/leagues/' in request.url.path:
                return httpx.Response(200,json={'data':{'league':{'id':'l_one','season':'2021/2022'},'matches':[match]}})
            return httpx.Response(200,json={'data':{'events':[]} if request.url.path.endswith('/events') else {}})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);setup_root(root)
            client=PitchClient(root/'data/pitchapi-cache',api_key='fixture-key',transport=httpx.MockTransport(endpoint))
            client.seed('/v1/matches/m_one/players',[])
            first=collect_arsenal(root,online=True,client=client)
            self.assertEqual(first['requests_used'],3)
            self.assertEqual(first['plan']['remaining_requests_before_retries'],2)
            self.assertEqual(first['complete_response_sets'],1)
            self.assertFalse(any(p=='/v1/matches/m_one' or p.endswith('/players') for p in calls))
            self.assertEqual(collect_arsenal(root,online=True,client=client)['requests_used'],3)
            self.assertEqual(len(calls),3)

    def test_pagination_and_incomplete_listing_stop_before_match_requests(self):
        for body in [
            {'league':{'id':'l_one','season':'2021/2022'},'matches':[],'pagination':{'has_more':True}},
            {'league':{'id':'l_one','season':'2021/2022'},'matches':[]}]:
            with self.subTest(body=body),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);setup_root(root)
                client=PitchClient(root/'data/pitchapi-cache',api_key='fixture-key',
                    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':body})))
                result=collect_arsenal(root,online=True,client=client)
                self.assertEqual(result['requests_used'],1)
                self.assertEqual(result['status'],'listing_validation_failed')

    def test_long_retry_after_and_missing_key_stop_without_unbounded_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);setup_root(root)
            client=PitchClient(root/'data/pitchapi-cache',api_key='',transport=httpx.MockTransport(
                lambda request:self.fail('Missing key must not send a request')))
            self.assertEqual(collect_arsenal(root,online=True,client=client)['requests_used'],0)
            client=PitchClient(root/'data/pitchapi-cache',api_key='fixture-key',transport=httpx.MockTransport(
                lambda request:httpx.Response(429,headers={'Retry-After':'600'},json={'error':{'code':'RATE_LIMIT_EXCEEDED'}})))
            result=collect_arsenal(root,online=True,client=client,wait=lambda seconds:self.fail('Must not shorten provider wait'))
            self.assertEqual(result['requests_used'],1)
            self.assertEqual(result['status'],'retry_after_exceeds_bounded_wait')

    def test_retry_attempts_count_toward_persistent_budget_and_cache_is_reused(self):
        calls = []
        def endpoint(request):
            calls.append(request.url.path)
            return httpx.Response(429,headers={'Retry-After':'0'},json={'error':{'code':'RATE_LIMIT_EXCEEDED'}})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); setup_root(root)
            client = PitchClient(root/'data/pitchapi-cache',api_key='fixture-key',transport=httpx.MockTransport(endpoint))
            first = collect_arsenal(root,online=True,max_requests=2,client=client,wait=lambda seconds:None)
            self.assertEqual(first['requests_used'],2)
            self.assertEqual(first['status'],'request_budget_reached')
            second = collect_arsenal(root,online=True,max_requests=2,client=client,wait=lambda seconds:None)
            self.assertEqual(second['requests_used'],2)
            self.assertEqual(len(calls),2)


if __name__=='__main__':
    unittest.main()
