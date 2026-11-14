"""Loss-aware source normalization. No inferred zeros for absent statistics."""
from collections import Counter
import math
import re
import json

FIELDS = {'minutes': 'minutes_played', 'goals':'goals', 'assists':'assists',
          'xg':'expected_goals', 'xa':'expected_assists'}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def assess_completeness(rows, audit):
    played = [row for row in rows if row.get('participation') == 'played']
    fields = ['minutes','goals','assists','yellow_cards','red_cards','xg','xa']
    missing = {key:sum(row.get(key) is None for row in played) if played else None for key in fields}
    accepted = set(audit.get('accepted_missing_fields', []))
    if accepted - {'goals','assists'}:
        raise ValueError('Only sparse goals/assists may be accepted by this audit; minutes remain required and card features are excluded')
    if not (audit.get('approved') is True and audit.get('source') and audit.get('notes')):
        accepted = set()
    blockers = []
    if not played:
        blockers.append('No complete played-player observations are available')
    for field in ['minutes','goals','assists']:
        if missing[field] and field not in accepted:
            blockers.append('Unaudited missing played-player statistic: '+field)
    return {'played_rows':len(played),'missing':missing,'accepted_missing_fields':sorted(accepted),
            'excluded_features':['yellow_cards','red_cards'],'blockers':blockers}


def normalize_match(match, players, events, *, fetched_at=None, lineups=None):
    if match.get('status') != 'finished':
        raise ValueError('Only completed matches can become performance rows')
    day = str(match.get('date') or match.get('time_utc', ''))[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('Completed match requires a source date')
    teams = {match.get(side, {}).get('id'): match.get(side, {}).get('name')
             for side in ['home_team','away_team']}
    yellow, red, second_yellow, substituted = Counter(), Counter(), Counter(), set()
    events_available = isinstance(events, dict) and isinstance(events.get('events'), list)
    card_errors = 0
    seen_cards = set()
    if events_available:
        for event in events['events']:
            kind = re.sub('[^a-z]', '', str(event.get('event_type', '')).lower())
            pid = (event.get('player') or {}).get('id')
            if kind in {'yellowcard','redcard','secondyellow','secondyellowcard','yellowredcard'}:
                fingerprint = json.dumps(event,sort_keys=True)
                if fingerprint in seen_cards:
                    card_errors += 1
                    continue
                seen_cards.add(fingerprint)
                if not pid:
                    card_errors += 1
                elif kind in {'secondyellow','secondyellowcard','yellowredcard'}:
                    yellow[pid] += 1
                    red[pid] += 1
                    second_yellow[pid] += 1
                else:
                    (yellow if kind == 'yellowcard' else red)[pid] += 1
                    if kind == 'redcard' and event.get('is_second_yellow') is True:
                        second_yellow[pid] += 1
            elif 'card' in kind or kind in {'yellow','red','secondyellow','yellowred'}:
                card_errors += 1
            if kind == 'substitution':
                sub_id = (event.get('sub_in_player') or {}).get('id')
                if sub_id:
                    substituted.add(sub_id)
    starters, bench = set(), set()
    if isinstance(lineups, dict):
        for side in ['home','away']:
            lineup = lineups.get(side, {})
            if lineup.get('confirmed') is True:
                starters.update(p['player_id'] for p in lineup.get('starters', []) if p.get('player_id'))
                bench.update(p['player_id'] for p in lineup.get('subs', []) if p.get('player_id'))
    rows, seen = [], set()
    for player in players:
        profile = player.get('player') or {}
        pid = profile.get('id')
        if not pid or pid in seen:
            raise ValueError('Missing or duplicate provider player identity in a match')
        seen.add(pid)
        raw, ignored = {}, 0
        for group in player.get('stats', []):
            entries = group.get('stats', {})
            if not isinstance(entries, dict):
                continue
            for entry in entries.values():
                key = entry.get('key') if isinstance(entry, dict) else None
                if not isinstance(key, str) or not key.strip():
                    ignored += 1
                    continue
                raw[str(group.get('key', 'unknown'))+'.'+key] = entry.get('stat', {})
        canonical = {field: number(raw.get('top_stats.'+key, {}).get('value'))
                     for field,key in FIELDS.items()}
        minutes = canonical['minutes']
        participation = 'played' if (minutes is not None and minutes > 0) or pid in starters or pid in substituted else 'unknown'
        if participation == 'unknown' and pid in bench and events_available:
            participation = 'unused_bench'
        row = {'provider_player_id': pid, 'provider_name':profile.get('name'),
            'provider_team_id':player.get('team_id'), 'club':teams.get(player.get('team_id')),
            'match_id':match['id'], 'date':day, 'league':'GB1',
            'position_id':profile.get('position_id', player.get('position_id')),
            'fetched_at':fetched_at, 'participation':participation,
            **canonical, 'yellow_cards':yellow[pid] if events_available and not card_errors else None,
            'red_cards':red[pid] if events_available and not card_errors else None,
            'second_yellow_sendoffs':second_yellow[pid] if events_available and not card_errors else None,
            'events_available':events_available, 'unresolved_card_events':card_errors,
            'ignored_empty_keys':ignored, 'raw_stats':raw,
            'card_semantics':'Explicit second-yellow events count as a booking and sendoff; a red-card second-yellow flag does not invent an additional booking. Provider semantics still require source audit.'}
        rows.append(row)
    return rows
