import unittest
from touchline.pitchapi_training import build_pilot_rows, fit_pilot_models
from touchline.pitchapi_data import assess_completeness
import pandas as pd
from pathlib import Path
import tempfile
from touchline.pitchapi import PitchClient, write_json
from touchline.pitchapi_arsenal import build_arsenal_pilot


class SmallCohortTests(unittest.TestCase):
    def test_quarantined_match_cannot_be_selected_even_as_the_only_cached_example(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root/'artifacts/pitchapi/arsenal_cohort.json',{
                'cached_match_id':'m_bad','quarantined_match_ids':['m_bad']})
            with self.assertRaisesRegex(ValueError,'quarantined'):
                build_arsenal_pilot(root)

    def test_cached_source_rows_are_not_presented_as_complete_training_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root/'artifacts/pitchapi/arsenal_cohort.json',{
                'club':'Arsenal','provider_team_id':'a','league_id':'l_one','season':'2021/2022',
                'target_date':'2022-06-15','cached_match_id':'m_one','quarantined_match_ids':['m_bad'],
                'official_match_report':'fixture official report','official_report_date':'2021-08-13',
                'players':[{'player_id':1,'name':'Fixture Person','provider_player_id':'p_one','profile_url':'fixture profile'}],
                'fixtures':[['2021-08-13','Opponent','away'],['2021-08-22','Other','home']]})
            write_json(root/'artifacts/players.json',[{'player_id':1,'name':'Fixture Person','club':'Current Club'}])
            write_json(root/'artifacts/history.json',{'1':[{'date':'2021-12-23','market_value_in_eur':900000},
                {'date':'2022-06-15','market_value_in_eur':1000000}]})
            write_json(root/'artifacts/pitchapi/status.json',{'sentinel':'original collection'})
            client = PitchClient(root/'data/pitchapi-cache',api_key='')
            match = {'id':'m_one','date':'2021-08-13','status':'finished','score_home':0,'score_away':0,
                     'home_team':{'id':'h','name':'Opponent'},'away_team':{'id':'a','name':'Arsenal'}}
            player = {'player':{'id':'p_one','name':'Fixture Person'},'team_id':'a','stats':[
                {'key':'top_stats','stats':{'minutes':{'key':'minutes_played','stat':{'value':90}},
                    'goals':{'key':'goals','stat':{'value':0}},'assists':{'key':'assists','stat':{'value':0}}}}]}
            for suffix,body in [('',match),('/players',[player]),('/events',{'events':[]}),
                                ('/lineups',{'away':{'confirmed':True,'starters':[{'player_id':'p_one'}]}})]:
                client.seed('/v1/matches/m_one'+suffix,body)
            result = build_arsenal_pilot(root)
            self.assertEqual(result['verified_players'],1)
            self.assertEqual(result['verified_source_rows'],1)
            self.assertEqual(result['eligible_training_rows'],0)
            self.assertEqual(result['request_plan']['recommended_requests'],4)
            self.assertEqual(result['targets'][0]['previous_value'],900000)
            self.assertEqual(result['targets'][0]['performance_window_start'],'2021-06-15')
            self.assertEqual(result['network_requests'],0)
            self.assertNotIn('yellow_cards',result['source_rows'][0])
            listing={'league':{'id':'l_one','season':'2021/2022'},'matches':[match,match|{
                'id':'m_two','date':'2021-08-22','home_team':{'id':'a','name':'Arsenal'},
                'away_team':{'id':'o','name':'Other'}}]}
            client.seed('/v1/leagues/l_one/matches',listing,params={'season':'2021/2022','status':'played'})
            player['team_id']='a'
            for suffix,body in [('/players',[player]),('/events',{'events':[]}),
                                ('/lineups',{'home':{'confirmed':True,'starters':[{'player_id':'p_one'}]}})]:
                client.seed('/v1/matches/m_two'+suffix,body)
            completed=build_arsenal_pilot(root)
            self.assertEqual(completed['eligible_training_rows'],1)
            self.assertEqual(completed['training_rows'][0]['minutes'],180)
            self.assertEqual(completed['training_rows'][0]['source_match_ids'],['m_one','m_two'])
            self.assertEqual(completed['training_rows'][0]['stats_through'],'2021-08-22')
            client.cache_path('/v1/matches/m_two/events').unlink()
            client.seed('/v1/matches/m_two/events',{'events':[{'event_type':'goal',
                'player':{'id':'p_one'},'team_id':'a','score_home':0,'score_away':0}]})
            inconsistent=build_arsenal_pilot(root)
            self.assertEqual(inconsistent['eligible_training_rows'],0)
            self.assertEqual(inconsistent['failed_player_ids'],[1])

    def test_verified_cohort_does_not_require_opponent_identities_or_card_features(self):
        appearances = [{'provider_player_id':pid,'match_id':str(i),'date':day,
            'participation':'played','minutes':90,'goals':0,'assists':0,
            'yellow_cards':None,'red_cards':None,'xg':None,'xa':None}
            for i,day in enumerate(['2021-08-13','2021-08-22']) for pid in ['p_one','p_unknown']]
        target = {'player_id':1,'date':'2022-06-15','actual_value':1000000,
                  'previous_value':900000,'previous_value_date':'2021-12-23'}
        mapping = [{'provider_player_id':'p_one','player_id':1,'status':'verified','evidence':[{'source':'fixture'}]}]
        coverage = [{'start':'2021-06-15','end_exclusive':'2022-06-15','complete':True,
                     'league':'GB1','player_ids':[1]}]
        result = build_pilot_rows(appearances,[target],mapping,coverage,cohort_player_ids={1})
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['minutes'],180)
        self.assertNotIn('yellow_cards',result['rows'][0])
        self.assertFalse(assess_completeness([appearances[0]],{})['blockers'])
        models = fit_pilot_models(pd.DataFrame(result['rows']))
        self.assertNotIn('red_cards',models['features'])
        self.assertNotIn('yellow_cards',models['change_features'])


if __name__=='__main__':
    unittest.main()
