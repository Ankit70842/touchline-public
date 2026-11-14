import tempfile
import unittest
from pathlib import Path
import httpx
from touchline.pitchapi import PitchClient, SourceUnavailable
from touchline.pitchapi_data import normalize_match, assess_completeness
from touchline.pitchapi_matching import resolve_player, build_mapping_registry
from touchline.pitchapi_training import build_pilot_rows, evaluate_pilot
from touchline.pitchapi_pilot import import_probe


class CacheTests(unittest.TestCase):
    def test_optional_analytics_404_is_not_a_required_source_failure(self):
        transport = httpx.MockTransport(lambda request:httpx.Response(404,
            json={'error':{'code':'ANALYTICS_UNAVAILABLE'}}))
        with tempfile.TemporaryDirectory() as folder:
            client = PitchClient(folder,api_key='fixture-secret',transport=transport)
            result = client.get('/v1/matches/m_one/advanced/players',online=True,optional=True)
            self.assertFalse(result['available'])
            self.assertFalse(list(Path(folder).glob('*.json')))

    def test_disallows_credential_query_parameters(self):
        with tempfile.TemporaryDirectory() as folder:
            client = PitchClient(folder,api_key='fixture-secret')
            with self.assertRaises(ValueError):
                client.get('/v1/leagues',{'api_key':'fixture-secret'})

    def test_probe_import_never_promotes_stat_summaries_to_complete_player_responses(self):
        report = {'checked_at_utc':'2026-11-13T00:00:00Z','catalog':[
            {'id':'l_pilot','name':'Premier League','country_code':'ENG','seasons':['2026/2027']}],
            'league_tests':[{'league':{'id':'l_pilot','name':'Premier League','country_code':'ENG'},
                'seasons':[{'requested':'2026/2027','samples':[{
                    'listing':{'id':'m_one','date':'2026-11-08','status':'finished'},
                    'detail':{'id':'m_one','date':'2026-11-08','status':'finished'},
                    'player_statistics':{'players_returned':40,'sample_player':{'id':'p_one','name':'A. Player'},
                                         'sample_stats':{'top_stats.goals':{'value':1}}}}]}]}]}
        with tempfile.TemporaryDirectory() as folder:
            client = PitchClient(folder)
            imported = import_probe(report,client)
            self.assertEqual(len(imported['partial_observations']),1)
            self.assertEqual(client.get('/v1/matches/m_one')['data']['date'],'2026-11-08')
            with self.assertRaises(SourceUnavailable):
                client.get('/v1/matches/m_one/players')

    def test_success_is_reused_offline_without_credentials_and_failures_are_not_cached(self):
        def endpoint(request):
            if request.url.path.endswith('/events'):
                return httpx.Response(503, json={'error': {'code': 'INTERNAL_SERVER_ERROR'}})
            return httpx.Response(200, json={'data': {'id': 'm_fixture', 'date': '2026-11-08'}})
        with tempfile.TemporaryDirectory() as folder:
            online = PitchClient(folder, api_key='fixture-secret', transport=httpx.MockTransport(endpoint))
            value = online.get('/v1/matches/m_fixture', online=True)
            self.assertEqual(value['data']['date'], '2026-11-08')
            self.assertNotIn('fixture-secret', ''.join(p.read_text() for p in Path(folder).glob('*.json')))
            offline = PitchClient(folder)
            self.assertEqual(offline.get('/v1/matches/m_fixture')['data'], value['data'])
            with self.assertRaises(SourceUnavailable):
                online.get('/v1/matches/m_fixture/events', online=True)
            with self.assertRaises(SourceUnavailable):
                offline.get('/v1/matches/m_fixture/events')


class NormalizationTests(unittest.TestCase):
    def test_position_dependent_missingness_requires_audited_acceptance_not_filled_zeros(self):
        row = {'participation':'played','minutes':90,'goals':None,'assists':None,
               'yellow_cards':0,'red_cards':0,'xg':None,'xa':None}
        self.assertTrue(assess_completeness([row],{})['blockers'])
        audit = {'approved':True,'source':'fixture field audit','notes':'Sparse outfield-only fields',
                 'accepted_missing_fields':['goals','assists']}
        assessment = assess_completeness([row],audit)
        self.assertFalse(assessment['blockers'])
        self.assertEqual(assessment['missing']['goals'],1)
        self.assertIsNone(row['goals'])

    def test_missing_values_empty_keys_and_cards_from_events(self):
        match = {'id':'m_one','date':'2024-03-01','status':'finished',
                 'home_team':{'id':'t_one','name':'Example FC'},
                 'away_team':{'id':'t_two','name':'Other FC'}}
        players = [{'player':{'id':'p_one','name':'Jane Player'},'team_id':'t_one',
            'stats':[{'key':'top_stats','stats':{
                'Minutes':{'key':'minutes_played','stat':{'type':'integer','value':90}},
                'Goals':{'key':'goals','stat':{'type':'integer','value':0}},
                'xG':{'key':'expected_goals','stat':{'type':'double','value':None}},
                'Broken':{'key':'','stat':{'type':'integer','value':999}}}}]}]
        events = {'events':[{'event_type':'YellowCard','player':{'id':'p_one'}},
                            {'event_type':'RedCard','player':{'id':'p_one'}}]}
        row = normalize_match(match, players, events, fetched_at='2026-11-13T00:00:00Z')[0]
        self.assertEqual(row['goals'],0)
        self.assertIsNone(row['assists'])
        self.assertIsNone(row['xg'])
        self.assertEqual((row['yellow_cards'],row['red_cards']),(1,1))
        self.assertEqual(row['ignored_empty_keys'],1)
        self.assertEqual(row['club'],'Example FC')
        self.assertIsNone(normalize_match(match,players,None)[0]['yellow_cards'])


class IdentityTests(unittest.TestCase):
    def test_out_of_scope_players_require_an_explicit_evidenced_decision(self):
        observation = {'provider_player_id':'p_old','provider_name':'Historic Player',
                       'club':'Example FC','date':'2021-01-01','match_id':'m_old'}
        manual = {'provider_player_id':'p_old','player_id':None,'status':'out_of_scope',
                  'method':'manual','evidence':[{'source':'fixture identity audit','reason':'No valuation labels in reference cohort'}]}
        decision = resolve_player(observation,[],manual)
        self.assertEqual(decision['status'],'out_of_scope')
        self.assertIsNone(decision['player_id'])

    def test_registry_preserves_each_observation_when_later_evidence_resolves_identity(self):
        references = [{'player_id':1,'name':'Alex Smith','club_evidence':[
            {'club':'Example FC','valid_from':'2024-01-01','valid_to':'2024-06-01',
             'verified':True,'source':'fixture roster'}]}]
        observations = [{'provider_player_id':'p_one','provider_name':'Alex Smith',
            'club':'Example FC','date':d,'match_id':m}
            for d,m in [('2021-01-01','m_old'),('2024-03-01','m_new')]]
        decision = build_mapping_registry(observations,references)[0]
        self.assertEqual(decision['status'],'verified')
        self.assertEqual([x['match_id'] for x in decision['observations']],['m_old','m_new'])

    def test_names_require_contemporaneous_club_evidence_and_ambiguities_stay_flagged(self):
        observation = {'provider_player_id':'p_one','provider_name':'Alex Smith',
                       'club':'Example FC','date':'2024-03-01','match_id':'m_one'}
        reference = {'player_id':1,'name':'Alex Smith','club':'Example FC'}
        self.assertEqual(resolve_player(observation,[reference])['status'],'needs_review')
        reference['club_evidence'] = [{'club':'Example FC','valid_from':'2024-01-01',
            'valid_to':'2024-06-01','source':'fixture dated roster','verified':True}]
        self.assertEqual(resolve_player(observation,[reference])['status'],'verified')
        self.assertEqual(resolve_player(observation|{'date':'2021-01-01'},[reference])['status'],'needs_review')
        twin = reference | {'player_id':2}
        self.assertEqual(resolve_player(observation,[reference,twin])['status'],'ambiguous')
        self.assertEqual(resolve_player(observation|{'provider_name':'A. Smith'},[reference])['status'],'needs_review')


class HistoricalRowTests(unittest.TestCase):
    def test_training_is_gated_and_selection_ignores_test_targets(self):
        rows = []
        for year in range(2022,2027):
            for i in range(2):
                rows.append({'player_id':i,'date':f'{year}-06-01','actual_value':1000000+i*100000,
                    'previous_value':1000000+i*100000,'previous_value_age_days':90,
                    'minutes':900,'appearances':10,'goals':2,'assists':1,
                    'yellow_cards':None,'red_cards':None,'xg':None,'xa':None,
                    'recent_minutes':90,'recent_goals':0,'recent_assists':0})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                evaluate_pilot(rows, {'ready_for_training':False}, folder, min_period_rows=2)
            first = evaluate_pilot(rows, {'ready_for_training':True}, folder, min_period_rows=2)
            changed_rows = [r|{'actual_value':9000000} if r['date'].startswith('2026') else r for r in rows]
            second = evaluate_pilot(changed_rows, {'ready_for_training':True}, folder, min_period_rows=2)
            self.assertEqual(first['selection'],second['selection'])
            self.assertEqual(first['interval'],second['interval'])
            self.assertEqual(first['selection']['selected'],'previous_value')
            self.assertEqual(first['results']['previous_value']['matched_history']['all']['mae_eur'],0)

    def test_pre_target_window_preserves_missing_totals_and_requires_coverage(self):
        appearances = [{'provider_player_id':'p_one','match_id':str(i),'date':d,
            'participation':'played','minutes':90,'goals':g,'assists':a,
            'yellow_cards':0,'red_cards':0,'xg':None,'xa':None}
            for i,(d,g,a) in enumerate([('2024-05-01',1,0),('2024-05-02',2,None),
                                        ('2024-06-01',999,99),('2024-06-02',888,88)])]
        mappings = [{'provider_player_id':'p_one','player_id':1,'status':'verified',
                     'method':'manual','evidence':[{'source':'fixture','reason':'known identity'}]}]
        targets = [{'player_id':1,'date':'2024-06-01','actual_value':1000000}]
        coverage = [{'start':'2023-06-01','end_exclusive':'2024-06-01','complete':True,'league':'GB1'}]
        output = build_pilot_rows(appearances,targets,mappings,coverage)
        row = output['rows'][0]
        self.assertEqual(row['minutes'],180)
        self.assertEqual(row['goals'],3)
        self.assertIsNone(row['assists'])
        self.assertIsNone(row['xg'])
        self.assertEqual(row['stats_through'],'2024-05-02')
        self.assertEqual(row['source_match_ids'],['0','1'])
        self.assertFalse(build_pilot_rows(appearances,targets,mappings,[])['rows'])


if __name__ == '__main__':
    unittest.main()
