"""Auditable identity decisions. A normalized name alone never verifies a player."""
from datetime import date
import re
import unicodedata


def name_key(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ' '.join(re.sub(r'[^\w\s]', ' ', ''.join(c for c in text if not unicodedata.combining(c))).split())


class IdentityIndex:
    """Build once per batch; aliases and provider links require explicit provenance."""
    def __init__(self, references):
        self.references = list(references)
        self.names, self.tokens, self.initials, self.links = {}, {}, {}, {}
        for r in self.references:
            names = [r['name']] + [a['name'] for a in r.get('name_aliases', [])
                                   if a.get('verified') is True and a.get('source')]
            for name in names:
                key = name_key(name); tokens = key.split()
                self.names.setdefault(key, {})[r['player_id']] = r
                for token in tokens:
                    self.tokens.setdefault(token, {})[r['player_id']] = r
                if tokens:
                    self.initials.setdefault((tokens[-1], tokens[0][0]), {})[r['player_id']] = r
            for link in r.get('provider_links', []):
                if link.get('verified') is True and link.get('source') and link.get('provider_player_id'):
                    self.links.setdefault(link['provider_player_id'], {})[r['player_id']] = (r, link)


def resolve_player(observation, references, manual=None, rejected=()):
    index = references if isinstance(references, IdentityIndex) else IdentityIndex(references)
    references = index.references
    provider_id = observation['provider_player_id']
    result = {'provider_player_id':provider_id, 'provider_name':observation.get('provider_name'),
        'player_id':None, 'status':'unmatched', 'method':None, 'candidate_ids':[],
        'observations':[{'match_id':observation.get('match_id'), 'date':observation.get('date'),
                         'club':observation.get('club')}], 'evidence':[]}
    if manual:
        identified = (manual.get('status') == 'verified'
                      and any(r['player_id'] == manual.get('player_id') for r in references))
        excluded = manual.get('status') == 'out_of_scope' and manual.get('player_id') is None
        valid = (manual.get('provider_player_id') == provider_id
                 and (identified or excluded)
                 and manual.get('method') == 'manual'
                 and manual.get('evidence')
                 and all(e.get('source') and e.get('reason') for e in manual['evidence']))
        if not valid:
            raise ValueError('Manual identity or out-of-scope decisions require explicit source/reason evidence')
        return result | {k:manual[k] for k in ['player_id','status','method','evidence']}
    supplied_names = {name_key(observation.get('provider_name')), name_key(observation.get('full_name'))} - {''}
    links = {pid:value for pid,value in index.links.get(provider_id, {}).items() if pid not in rejected}
    if links:
        result['candidate_ids'] = sorted(links)
        if len(links) > 1:
            return result | {'status':'conflict', 'method':'conflicting_provider_links'}
        pid, (_, evidence) = next(iter(links.items()))
        return result | {'status':'verified','player_id':pid,'method':'reviewed_stable_provider_id','evidence':[evidence]}
    exact_by_id = {pid:r for name in supplied_names for pid,r in index.names.get(name, {}).items() if pid not in rejected}
    exact = list(exact_by_id.values())
    # Initials may suggest a review candidate, but cannot verify identity.
    tokens = name_key(observation.get('provider_name')).split()
    suggested = (index.tokens.get(tokens[0], {}) if len(tokens)==1 else
                 index.initials.get((tokens[-1],tokens[0][0]), {}) if tokens else {})
    possible = exact or [r for pid,r in suggested.items() if pid not in rejected]
    result['candidate_ids'] = sorted({r['player_id'] for r in possible})
    supported = []
    for reference in exact:
        for evidence in reference.get('club_evidence', []):
            if not (evidence.get('verified') is True and evidence.get('source')
                    and evidence.get('valid_from') and evidence.get('valid_to')):
                continue
            day = date.fromisoformat(observation['date'])
            start, end = date.fromisoformat(evidence['valid_from']), date.fromisoformat(evidence['valid_to'])
            team_matches = (evidence.get('provider_team_id') == observation.get('provider_team_id')
                            if evidence.get('provider_team_id') else
                            bool(observation.get('club')) and name_key(evidence.get('club')) == name_key(observation['club']))
            if start <= day <= end and team_matches:
                supported.append((reference['player_id'], evidence))
    identities = {pid for pid, _ in supported}
    if len(identities) == 1:
        result.update(player_id=next(iter(identities)), status='verified', method='full_name_and_dated_club',
                      evidence=[e for _,e in supported])
    elif len(identities) > 1 or len(possible) > 1:
        result.update(status='ambiguous', method='review_required')
    elif possible:
        result.update(status='needs_review', method='missing_full_name_or_dated_club_evidence')
    return result


def build_mapping_registry(observations, references, manual=(), rejected=None):
    references = IdentityIndex(references)
    overrides = {item['provider_player_id']: item for item in manual}
    if len(overrides) != len(manual):
        raise ValueError('Duplicate manual provider mapping')
    registry = {}
    for observation in observations:
        pid = observation['provider_player_id']
        decision = resolve_player(observation, references, overrides.get(pid), (rejected or {}).get(pid, ()))
        if pid not in registry:
            registry[pid] = decision
            continue
        previous = registry[pid]
        new_observations = list(decision['observations'])
        candidates = sorted(set(previous['candidate_ids']) | set(decision['candidate_ids']))
        verified_ids = {r['player_id'] for r in [previous,decision] if r['status'] == 'verified'}
        if len(verified_ids) > 1 or previous['status'] == 'conflict' or decision['status']=='conflict':
            previous.update(status='conflict', player_id=None, method='conflicting_identity_evidence')
        elif decision['status'] == 'verified' and previous['status'] != 'verified':
            old_observations = previous['observations']
            registry[pid] = decision
            previous = registry[pid]
            previous['observations'] = old_observations
        previous['observations'].extend(new_observations)
        previous['candidate_ids'] = candidates
    # One reference ID must not silently absorb multiple provider IDs.
    by_reference = {}
    for value in registry.values():
        if value['status'] == 'verified':
            by_reference.setdefault(value['player_id'], []).append(value)
    for values in by_reference.values():
        if len(values) > 1:
            for value in values:
                value.update(status='conflict', player_id=None, method='multiple_provider_ids_for_reference')
    return list(registry.values())
