"""Bounded, resumable Arsenal-only acquisition. No training and no expansion."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
from touchline.pitchapi import PitchClient, SourceUnavailable, write_json
from touchline.pitchapi_matching import name_key
from touchline.pitchapi_review import read

ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION = 'arsenal-three-player-2026-11-14'
SUFFIXES = ['/players','/events','/lineups']
ALIASES = {'man city':'manchester city','man utd':'manchester united','spurs':'tottenham hotspur',
           'manchester utd':'manchester united','brighton hove albion':'brighton',
           'tottenham':'tottenham hotspur','brighton and hove albion':'brighton',
           'wolverhampton wanderers':'wolves','norwich city':'norwich',
           'leeds united':'leeds','west ham united':'west ham','newcastle united':'newcastle',
           'leicester city':'leicester'}


def team_key(name):
    key = name_key(name)
    return ALIASES.get(key,key)


def resolve_listing(body, cohort):
    """No undocumented page/cursor requests: verify the entire club checklist."""
    if not isinstance(body,dict) or body.get('league',{}).get('id')!=cohort['league_id'] or body.get('league',{}).get('season')!=cohort['season']:
        raise ValueError('LISTING_SEASON_OR_LEAGUE_MISMATCH')
    for container in [body,body.get('pagination',{}),body.get('meta',{}),body.get('links',{})]:
        if not isinstance(container,dict):
            raise ValueError('UNSUPPORTED_PAGINATION')
        if any(container.get(k) for k in ['next','next_page','next_cursor','has_more']):
            raise ValueError('UNSUPPORTED_PAGINATION')
        if container.get('total_pages',1)!=1:
            raise ValueError('UNSUPPORTED_PAGINATION')
    expected = {(d,team_key(opponent),venue) for d,opponent,venue in cohort['fixtures']}
    if len(expected)!=len(cohort['fixtures']):
        raise ValueError('DUPLICATE_EXPECTED_FIXTURE')
    matches, observed, ids = [],set(),set()
    if not isinstance(body.get('matches'),list):
        raise ValueError('INVALID_MATCH_LIST')
    for match in body['matches']:
        home,away = match.get('home_team',{}),match.get('away_team',{})
        if cohort['provider_team_id'] not in [home.get('id'),away.get('id')]:
            continue
        venue,other = ('home',away) if home.get('id')==cohort['provider_team_id'] else ('away',home)
        identity = (match.get('date'),team_key(other.get('name')),venue)
        if identity not in expected or identity in observed or not match.get('id') or match['id'] in ids or match.get('status')!='finished':
            raise ValueError('FIXTURE_ID_DATE_OR_OPPONENT_MISMATCH')
        if any(not isinstance(match.get(k),int) or isinstance(match.get(k),bool) or match[k]<0 for k in ['score_home','score_away']):
            raise ValueError('INVALID_FINISHED_SCORE')
        if match['id'] in cohort['quarantined_match_ids']:
            raise ValueError('QUARANTINED_FIXTURE')
        matches.append(match); observed.add(identity); ids.add(match['id'])
    if observed!=expected:
        raise ValueError('INCOMPLETE_CLUB_FIXTURE_LIST')
    return sorted(matches,key=lambda m:(m['date'],m['id']))


def collect_arsenal(root=ROOT, *, online=False, max_requests=170, client=None, wait=time.sleep):
    root = Path(root)
    if not 0<=max_requests<=170:
        raise ValueError('This authorization permits a conservative maximum of 170 total attempts')
    local = root/'data/pitchapi-local'; local.mkdir(parents=True,exist_ok=True)
    state_path = local/'arsenal_collection_state.json'
    lock = local/'arsenal_collection.lock'
    try:
        fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY); os.close(fd)
    except FileExistsError:
        raise ValueError('Collection is active or interrupted; inspect arsenal_collection.lock before retrying') from None
    try:
        state = read(state_path,{'authorization':AUTHORIZATION,'budget':max_requests,'attempts':[]})
        if state['authorization']!=AUTHORIZATION:
            raise ValueError('Collection ledger belongs to a different authorization')
        state['budget'] = min(state['budget'],max_requests)
        client = client or PitchClient(root/'data/pitchapi-cache')
        cohort = read(root/'artifacts/pitchapi/arsenal_cohort.json',{})
        status, issues, matches = 'collecting',[],[]
        def get(path,params=None):
            nonlocal status
            try:
                return client.get(path,params)  # Always validate cached successes first.
            except SourceUnavailable as error:
                if error.code!='OFFLINE_CACHE_MISS':
                    issues.append({'path':path,'code':error.code}); return None
            if not online:
                issues.append({'path':path,'code':'OFFLINE_CACHE_MISS'}); return None
            if not client.api_key:
                status = 'api_key_not_visible'; return None
            for retry in range(3):
                if len(state['attempts'])>=state['budget']:
                    status = 'request_budget_reached'; return None
                attempt = {'path':path,'params':params or {},'started_at':datetime.now(timezone.utc).isoformat(),
                           'outcome':'reserved_unknown_if_interrupted'}
                state['attempts'].append(attempt)
                write_json(state_path,state)  # Crash-safe conservative reservation.
                try:
                    value = client.get(path,params,online=True)
                    attempt['outcome']='success'; write_json(state_path,state)
                    return value
                except SourceUnavailable as error:
                    attempt.update(outcome=error.code,http_status=error.status); write_json(state_path,state)
                    if error.status in {401,403}:
                        status='authentication_failed'; return None
                    transient = error.status==429 or (error.status is not None and error.status>=500) or error.code in {'ConnectError','ReadTimeout','ConnectTimeout'}
                    if not transient:
                        issues.append({'path':path,'code':error.code}); return None
                    delay = error.retry_after if error.retry_after is not None else 2**retry
                    if not math.isfinite(delay) or delay>30:
                        status='retry_after_exceeds_bounded_wait'; return None
                    if retry==2:
                        status='bounded_retries_exhausted'; return None
                    wait(delay)
            return None
        listing_path = '/v1/leagues/'+cohort['league_id']+'/matches'
        listing = get(listing_path,{'season':cohort['season'],'status':'played'})
        if listing:
            try:
                matches = resolve_listing(listing['data'],cohort)
            except ValueError as error:
                status='listing_validation_failed'; issues.append({'path':listing_path,'code':str(error)})
        remaining = []
        def valid_cache(path):
            try:
                client.get(path)
                return True
            except SourceUnavailable:
                return False
        for match in matches:
            for suffix in SUFFIXES:
                path = '/v1/matches/'+match['id']+suffix
                if not valid_cache(path):
                    remaining.append(path)
        plan = {'listing_validated':bool(matches),'pagination':'No continuation advertised; complete club fixture checklist verified' if matches else 'Not verified',
                'resolved_matches':len(matches),'missing_paths_after_listing':remaining,
                'remaining_requests_before_retries':len(remaining) if matches else None,'requests_used_at_plan':len(state['attempts']),
                'detail_requests_avoided':'Season listing supplies dates, teams, status and final scores; do not refetch per-match details'}
        # Publish the recalculated cost before fetching any match bodies.
        write_json(local/'arsenal_match_plan.json',{'matches':matches,'listing_source':
            {k:listing[k] for k in ['path','params','fetched_at','data_sha256']} if listing else None,'plan':plan})
        print(json.dumps({'phase':'listing_plan','status':status,'resolved_matches':len(matches),
                          'requests_used':len(state['attempts']),'remaining_before_retries':len(remaining) if matches else None}),flush=True)
        if status=='collecting':
            for match in matches:
                for suffix in SUFFIXES:
                    get('/v1/matches/'+match['id']+suffix)
                    if status!='collecting':
                        break
                if status!='collecting':
                    break
                print(json.dumps({'phase':'match_cached','match_id':match['id'],'requests_used':len(state['attempts'])}),flush=True)
        completed = sum(all(valid_cache('/v1/matches/'+m['id']+s) for s in SUFFIXES) for m in matches)
        if not matches and all(valid_cache('/v1/matches/'+cohort['cached_match_id']+s) for s in SUFFIXES):
            completed=1
        if status=='collecting':
            status='responses_cached' if matches and completed==len(matches) else 'missing_responses'
        report = {'authorization':AUTHORIZATION,'status':status,'requests_used':len(state['attempts']),
            'request_budget':state['budget'],'requests_remaining':max(0,state['budget']-len(state['attempts'])),
            'complete_response_sets':completed,'expected_matches':len(cohort['fixtures']),
            'plan':plan,'issues':issues,'scope':'2021/22 Arsenal Premier League only; cups and internationals excluded',
            'production_model_changed':False,'uncertain_reservations':sum(a['outcome']=='reserved_unknown_if_interrupted' for a in state['attempts'])}
        write_json(state_path,state)
        write_json(root/'artifacts/pitchapi/arsenal_collection.json',report)
        return report
    finally:
        lock.unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online',action='store_true')
    parser.add_argument('--max-requests',type=int,default=170)
    args=parser.parse_args()
    result=collect_arsenal(online=args.online,max_requests=args.max_requests)
    from touchline.pitchapi_arsenal import build_arsenal_pilot
    exported=build_arsenal_pilot()
    print(json.dumps({k:result[k] for k in ['status','requests_used','request_budget','complete_response_sets']}
        | {'eligible_training_rows':exported['eligible_training_rows'],'excluded_targets':exported['excluded_targets']},indent=2))
    raise SystemExit(0 if result['status']=='responses_cached' else 2)
