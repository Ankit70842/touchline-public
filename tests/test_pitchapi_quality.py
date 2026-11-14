import unittest
from touchline.pitchapi_quality import audit_match
from touchline.pitchapi_data import normalize_match
from touchline.pitchapi_matching import resolve_player, build_mapping_registry


class EventQualityTests(unittest.TestCase):
    def test_own_goal_event_team_requires_opposing_actor_membership_and_consistent_score(self):
        match={'id':'m_fixture','score_home':1,'score_away':0,
               'home_team':{'id':'h'},'away_team':{'id':'a'}}
        event={'event_type':'goal','minute':55,'team_id':'h','player':{'id':'defender'},
               'is_own_goal':True,'score_home':0,'score_away':0}
        players=[{'provider_player_id':'defender','provider_team_id':'a','goals':0}]
        result=audit_match(match,{'events':[event]},players)
        self.assertTrue(result['passed'])
        self.assertEqual(result['own_goal_beneficiary_evidence'][0]['beneficiary_team_id'],'h')
        self.assertEqual(result['actor_goal_discrepancies'],[])
        self.assertFalse(audit_match(match,{'events':[event]},[])['passed'])
        self.assertFalse(audit_match(match,{'events':[event]},[players[0]|{'provider_team_id':'h'}])['passed'])
        self.assertFalse(audit_match(match|{'score_home':2},{'events':[event]},players)['passed'])

    def test_exact_goal_duplicates_are_not_silently_accepted(self):
        match = {'id':'m_one','score_home':1,'score_away':0,
                 'home_team':{'id':'h'},'away_team':{'id':'a'}}
        goal = {'event_type':'goal','minute':1,'team_id':'h','player':{'id':'p'},'score_home':0,'score_away':0}
        result = audit_match(match,{'events':[goal,dict(goal)]},[])
        self.assertFalse(result['passed'])
        self.assertEqual(result['exact_duplicate_goal_groups'],[[0,1]])

    def test_flagged_red_does_not_invent_a_booking_and_empty_keys_stay_ignored(self):
        match = {'id':'m_one','date':'2024-01-01','status':'finished',
                 'home_team':{'id':'h'},'away_team':{'id':'a'}}
        player = {'player':{'id':'p','name':'Fixture'},'team_id':'h',
                  'stats':[{'key':'top_stats','stats':{'bad':{'key':'','stat':{'value':99}}}}]}
        events = {'events':[{'event_type':'redcard','player':{'id':'p'},'is_second_yellow':True}]}
        row = normalize_match(match,[player],events)[0]
        self.assertEqual((row['yellow_cards'],row['red_cards'],row['second_yellow_sendoffs']),(0,1,1))
        self.assertEqual(row['ignored_empty_keys'],1)
        self.assertIsNone(row['goals'])
        events['events'].append(dict(events['events'][0]))
        self.assertIsNone(normalize_match(match,[player],events)[0]['red_cards'])

    def test_explicit_own_goal_and_disallowed_goal_have_distinct_accounting(self):
        match = {'id':'m_one','date':'2024-01-01','status':'finished','score_home':1,'score_away':0,
                 'home_team':{'id':'h'},'away_team':{'id':'a'}}
        events = {'events':[
            {'event_type':'goal','minute':1,'team_id':'h','player':{'id':'scorer'},
             'score_home':0,'score_away':0,'is_disallowed':True},
            {'event_type':'goal','minute':5,'team_id':'a','beneficiary_team_id':'h',
             'player':{'id':'defender'},'is_own_goal':True,'score_home':0,'score_away':0}]}
        result = audit_match(match,events,[{'provider_player_id':'defender','goals':0}])
        self.assertTrue(result['passed'])
        self.assertEqual(result['explicit_disallowed_event_indices'],[0])
        self.assertEqual(result['own_goal_event_indices'],[1])
        self.assertFalse(result['actor_goal_discrepancies'])
        del events['events'][1]['beneficiary_team_id']
        self.assertFalse(audit_match(match,events,[])['passed'])

    def test_second_yellow_and_substitution_do_not_invent_missing_stats(self):
        match = {'id':'m_one','date':'2024-01-01','status':'finished',
                 'home_team':{'id':'h'},'away_team':{'id':'a'}}
        player = {'player':{'id':'p','name':'Fixture'},'team_id':'h','stats':[]}
        events = {'events':[
            {'event_type':'yellowcard','player':{'id':'p'}},
            {'event_type':'secondyellow','player':{'id':'p'}},
            {'event_type':'substitution','player':{'id':'off'},'sub_in_player':{'id':'p'}}]}
        row = normalize_match(match,[player],events)[0]
        self.assertEqual(row['participation'],'played')
        self.assertIsNone(row['minutes'])
        self.assertIsNone(row['goals'])
        self.assertEqual((row['yellow_cards'],row['red_cards']),(2,1))
        self.assertEqual(row['second_yellow_sendoffs'],1)

    def test_near_duplicate_goals_are_quarantined_not_silently_deleted(self):
        match = {'id':'m_one','score_home':0,'score_away':1,
                 'home_team':{'id':'h'},'away_team':{'id':'a'}}
        goals = [{'event_type':'goal','minute':m,'minute_added':0,'team_id':'a',
                  'player':{'id':'p'},'score_home':0,'score_away':0,
                  'is_own_goal':False,'is_penalty':False} for m in [1,2]]
        players = [{'provider_player_id':'p','provider_team_id':'a','goals':1}]
        result = audit_match(match,{'events':goals},players)
        self.assertFalse(result['passed'])
        self.assertEqual(result['exact_duplicate_goal_groups'],[])
        self.assertEqual(result['suspected_goal_groups'],[[0,1]])
        self.assertEqual(result['single_event_removal_reconciliations'],[0,1])
        self.assertEqual(len(goals),2)


class ScalableIdentityTests(unittest.TestCase):
    def test_rejected_candidates_stay_excluded_and_conflicts_do_not_remain_verified(self):
        reference = {'player_id':1,'name':'Fixture Person','club_evidence':[
            {'club':'Old Club','valid_from':'2020-01-01','valid_to':'2021-12-31','verified':True,'source':'fixture'}]}
        observation = {'provider_player_id':'p_a','provider_name':'Fixture Person','date':'2021-08-13','club':'Old Club'}
        self.assertEqual(resolve_player(observation,[reference],rejected={1})['status'],'unmatched')
        registry = build_mapping_registry([observation,observation|{'date':'2026-11-08','club':'New Club'}],[reference])
        self.assertEqual(registry[0]['status'],'verified')
        self.assertEqual(len(registry[0]['observations']),2)

    def test_short_name_only_suggests_until_reviewed_alias_and_dated_team_link_exist(self):
        observation = {'provider_player_id':'p_r','provider_name':'Reinildo',
                       'provider_team_id':'t_s','club':'Sunderland','date':'2026-11-08','match_id':'m_a'}
        reference = {'player_id':42,'name':'Reinildo Mandava','club':'Sunderland AFC'}
        candidate = resolve_player(observation,[reference])
        self.assertEqual(candidate['candidate_ids'],[42])
        self.assertEqual(candidate['status'],'needs_review')
        reference.update(name_aliases=[{'name':'Reinildo','source':'fixture reviewed alias','verified':True}],
            club_evidence=[{'club':'Sunderland AFC','provider_team_id':'t_s','valid_from':'2026-07-01',
                'valid_to':'2027-06-30','source':'fixture dated membership','verified':True}])
        self.assertEqual(resolve_player(observation,[reference])['status'],'verified')
        self.assertEqual(resolve_player(observation|{'date':'2021-08-13'},[reference])['status'],'needs_review')

    def test_stable_provider_link_survives_display_name_change_but_conflicts_are_flagged(self):
        link = {'provider_player_id':'p_one','source':'fixture approved crosswalk','verified':True}
        reference = {'player_id':1,'name':'Original Name','provider_links':[link]}
        observation = {'provider_player_id':'p_one','provider_name':'Changed display name',
                       'date':'2026-11-08','club':'New Club','match_id':'m_a'}
        result = resolve_player(observation,[reference])
        self.assertEqual((result['status'],result['player_id']),('verified',1))
        self.assertEqual(resolve_player(observation,[reference,reference|{'player_id':2}])['status'],'conflict')


if __name__ == '__main__':
    unittest.main()
