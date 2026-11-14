"""Offline evidence checks. Suspect events are retained, never silently repaired."""
from collections import Counter, defaultdict
import json


def event_kind(event):
    return ''.join(c for c in str(event.get('event_type','')).casefold() if c.isalpha())


def disallowed(event):
    return (event.get('is_disallowed') is True or event.get('is_cancelled') is True
            or event.get('status') in {'disallowed','cancelled'})


def audit_match(match, events, players):
    entries = events.get('events',[]) if isinstance(events,dict) else []
    home, away = match['home_team']['id'], match['away_team']['id']
    final = (match.get('score_home'),match.get('score_away'))
    goal_indices = [i for i,e in enumerate(entries) if event_kind(e)=='goal']
    allowed = [i for i in goal_indices if not disallowed(entries[i])]
    exact, similar = defaultdict(list), defaultdict(list)
    for i in allowed:
        e = entries[i]
        exact[json.dumps(e,sort_keys=True)].append(i)
        signature = (e.get('player',{}).get('id'),e.get('team_id'),e.get('score_home'),
                     e.get('score_away'),e.get('is_own_goal'),e.get('is_penalty'))
        similar[signature].append(i)
    exact_groups = [v for v in exact.values() if len(v)>1]
    suspected = [v for v in similar.values() if len(v)>1 and v not in exact_groups]
    actor_teams = defaultdict(set)
    for player in players:
        if player.get('provider_team_id') in {home,away}:
            actor_teams[player['provider_player_id']].add(player['provider_team_id'])
    def beneficiary(e):
        explicit=e.get('beneficiary_team_id') or e.get('scoring_team_id')
        if explicit:
            return explicit,'explicit_beneficiary_field'
        teams=actor_teams[e.get('player',{}).get('id')]
        # Cached own goals credit the event's team while the actor belongs to
        # the opponent in the same match's player response. Require both facts;
        # do not infer a beneficiary merely to make the final score add up.
        if len(teams)==1 and e.get('team_id') in {home,away} and e['team_id'] not in teams:
            return e['team_id'],'event_team_corroborated_by_opposing_actor_membership'
        return None,'unresolved'
    def side(e):
        if e.get('is_own_goal'):
            tid,_ = beneficiary(e)
        else:
            tid = e.get('team_id')
        return 0 if tid==home else 1 if tid==away else None
    def trace(indices, timing):
        cursor = [0,0]
        for i in indices:
            e = entries[i]; team = side(e)
            if team is None:
                return False
            score = (e.get('score_home'),e.get('score_away'))
            if timing=='before' and score!=tuple(cursor):
                return False
            cursor[team] += 1
            if timing=='after' and score!=tuple(cursor):
                return False
        return tuple(cursor)==final
    timing = [t for t in ['before','after'] if trace(allowed,t)]
    removals = [i for i in allowed if any(trace([j for j in allowed if j!=i],t)
                                         for t in ['before','after'])] if not timing else []
    actor_counts = Counter(entries[i].get('player',{}).get('id') for i in allowed
                           if not entries[i].get('is_own_goal'))
    differences = []
    for player in players:
        pid, value = player['provider_player_id'],player.get('goals')
        if value is not None and value!=actor_counts[pid]:
            differences.append({'provider_player_id':pid,'name':player.get('provider_name'),
                'recorded_player_goals':value,'goal_tagged_events':actor_counts[pid]})
    own = [i for i in allowed if entries[i].get('is_own_goal')]
    blockers = []
    if not timing:
        blockers.append('Goal events do not form a complete consistent before/after-score progression')
    if exact_groups or suspected:
        blockers.append('Duplicate or near-duplicate goal evidence requires review; no entry was removed')
    if differences:
        blockers.append('Player goal totals and goal-tagged actor counts differ')
    if any(side(entries[i]) is None for i in own):
        blockers.append('Own-goal beneficiary convention is not established by source evidence')
    return {'match_id':match['id'],'date':match.get('date'),'final_score':list(final),
        'passed':not blockers,'blockers':blockers,'goal_tagged_events':len(goal_indices),
        'explicit_disallowed_event_indices':[i for i in goal_indices if disallowed(entries[i])],
        'own_goal_event_indices':own,'penalty_goal_event_indices':[i for i in allowed if entries[i].get('is_penalty')],
        'own_goal_beneficiary_evidence':[{'source_event_index':i,'beneficiary_team_id':beneficiary(entries[i])[0],
            'method':beneficiary(entries[i])[1],
            'actor_team_ids':sorted(actor_teams[entries[i].get('player',{}).get('id')])} for i in own],
        'exact_duplicate_goal_groups':exact_groups,'suspected_goal_groups':suspected,
        'consistent_score_timing':timing,'single_event_removal_reconciliations':removals,
        'actor_goal_discrepancies':differences,
        'observed_player_goal_total':sum(p['goals'] for p in players if p.get('goals') is not None),
        'players_without_goal_field':sum(p.get('goals') is None for p in players),
        'goal_evidence':[{'source_event_index':i,**entries[i]} for i in goal_indices],
        'interpretation':'Single-removal reconciliations are diagnostic alternatives, not permission to delete an event.'}
