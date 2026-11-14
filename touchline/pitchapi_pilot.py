"""Resumable Premier League pilot; offline by default, never expands implicitly."""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
from touchline.pitchapi import PitchClient, SourceUnavailable, write_json
from touchline.pitchapi_data import normalize_match, assess_completeness
from touchline.pitchapi_matching import build_mapping_registry, name_key
from touchline.pitchapi_quality import audit_match
from touchline.pitchapi_review import rejected_candidates
from touchline.pitchapi_training import build_pilot_rows, evaluate_pilot
from touchline.valuation import build_history_snapshots

ROOT = Path(__file__).resolve().parents[1]


def import_probe(report, client):
    """Only retained full bodies become response-cache entries."""
    timestamp = report.get('checked_at_utc')
    catalog = report.get('catalog', [])
    if catalog:
        client.seed('/v1/leagues',{'leagues':catalog},fetched_at=timestamp,provenance='probe_full_body')
    partial, matches, summary = [], {}, []
    for league in report.get('league_tests', []):
        if name_key(league.get('league', {}).get('name')) != 'premier league':
            continue
        for season in league.get('seasons', []):
            summary.append({k:season.get(k) for k in ['requested','returned_matches',
                'first_completed_date','last_completed_date','returned_season_matches_request']})
            for sample in season.get('samples', []):
                match = sample.get('detail') or sample.get('listing')
                if not match or not match.get('id'):
                    continue
                mid = match['id']
                if sample.get('detail'):
                    client.seed('/v1/matches/'+mid,sample['detail'],fetched_at=timestamp,provenance='probe_full_body')
                matches[mid] = match
                profile = sample.get('player_profile')
                if profile and profile.get('id'):
                    client.seed('/v1/players/'+profile['id'],profile,fetched_at=timestamp,provenance='probe_full_body')
                example = sample.get('player_statistics', {}).get('sample_player') or {}
                if example.get('id'):
                    partial.append({'provider_player_id':example['id'],'provider_name':example.get('name'),
                        'full_name':profile.get('name') if profile and profile.get('id') == example['id'] else None,
                        'club':None,'date':str(match.get('date') or match.get('time_utc',''))[:10],
                        'match_id':mid,'partial_probe_example':True,
                        'reason':'Team ID and remaining player rows were not retained by the probe'})
    return {'partial_observations':partial,'matches':list(matches.values()),'listing_summary':summary,
            'probe_run_started_at':timestamp,'timestamp_precision':'Probe run start, not individual response completion'}


def run_pilot(*, probe_report=None, online=False, full=False, max_requests=50,
              as_of='2026-11-13', root=ROOT):
    root = Path(root)
    client = PitchClient(root/'data/pitchapi-cache')
    local = root/'data/pitchapi-local'
    artifacts = root/'artifacts/pitchapi'
    report = json.loads(Path(probe_report).read_text(encoding='utf-8')) if probe_report else {}
    imported = import_probe(report,client)
    issues = []
    network_blocked = False
    def get(path,params=None):
        nonlocal network_blocked
        try:
            cached = client.cache_path(path,params).exists()
            if online and not cached and client.network_requests >= max_requests:
                raise SourceUnavailable('REQUEST_BUDGET_REACHED',path)
            return client.get(path,params,online=online and not network_blocked)
        except SourceUnavailable as error:
            issues.append({'path':path,'params':params or {},'code':error.code})
            if error.status in {401,403,429}:
                network_blocked = True
            return None
    catalog = get('/v1/leagues')
    leagues = catalog['data'].get('leagues',[]) if catalog else []
    candidates = [l for l in leagues if name_key(l.get('name')) == 'premier league'
                  and str(l.get('country_code','')).upper() in {'ENG','GB','GBR'}]
    league = candidates[0] if len(candidates) == 1 else None
    matches = {m['id']:m for m in imported['matches']
               if str(m.get('date') or m.get('time_utc',''))[:10] <= as_of}
    seasons = [f'{year}/{year+1}' for year in range(2021,2027)]
    complete_listings = []
    listing_fetched_at = {}
    if full and league:
        for season in seasons:
            envelope = get(f"/v1/leagues/{league['id']}/matches",{'season':season,'status':'played'})
            if not envelope:
                continue
            body = envelope['data']
            if not isinstance(body,dict) or body.get('league',{}).get('season') != season or not isinstance(body.get('matches'),list):
                issues.append({'path':f"/v1/leagues/{league['id']}/matches",'code':'SEASON_OR_SCHEMA_MISMATCH'})
                continue
            complete_listings.append(season)
            listing_fetched_at[season] = envelope['fetched_at']
            for m in body['matches']:
                day = str(m.get('date') or m.get('time_utc',''))[:10]
                if m.get('status') == 'finished' and day and day <= as_of:
                    matches[m['id']] = m
    players = json.loads((root/'artifacts/players.json').read_text(encoding='utf-8'))
    reference_path = local/'identity_evidence.json'
    extra = json.loads(reference_path.read_text(encoding='utf-8')) if reference_path.exists() else []
    evidence = {r['player_id']:r for r in extra}
    references = [{'player_id':p['player_id'],'name':p['name'],'club':p['club'],
                   'club_snapshot_date':p['date'], **evidence.get(p['player_id'],{})} for p in players]
    manual_path = local/'manual_mappings.json'
    manual = json.loads(manual_path.read_text(encoding='utf-8')) if manual_path.exists() else []
    completeness_path = local/'completeness_audit.json'
    completeness_audit = json.loads(completeness_path.read_text(encoding='utf-8')) if completeness_path.exists() else {}
    observations, fetched_dates, completed, quality_blockers = [], [], [], []
    for mid, listing in sorted(matches.items(),key=lambda item:str(item[1].get('date') or item[1].get('time_utc',''))):
        detail, stats = get('/v1/matches/'+mid), get(f'/v1/matches/{mid}/players')
        events, lineups = get(f'/v1/matches/{mid}/events'), get(f'/v1/matches/{mid}/lineups')
        if not detail or not stats:
            continue
        match = detail['data']
        if league and match.get('league',{}).get('id') != league['id']:
            issues.append({'path':'/v1/matches/'+mid,'code':'MATCH_LEAGUE_NOT_VERIFIED'})
            continue
        try:
            rows = normalize_match(match,stats['data'],events['data'] if events else None,
                fetched_at=stats['fetched_at'],lineups=lineups['data'] if lineups else None)
        except (ValueError,TypeError,KeyError):
            issues.append({'path':f'/v1/matches/{mid}/players','code':'NORMALIZATION_REVIEW_REQUIRED'})
            continue
        for row in rows:
            profile = get('/v1/players/'+row['provider_player_id']) if '.' in str(row.get('provider_name','')) else None
            if profile:
                row['full_name'] = profile['data'].get('name')
        observations.extend(rows)
        if events:
            quality = audit_match(match, events['data'], rows)
            quality_blockers.extend(mid+': '+message for message in quality['blockers'])
        fetched_dates.append(stats['fetched_at'])
        if events and lineups:
            completed.append(mid)
    full_ids = {row['provider_player_id'] for row in observations}
    partial = [row for row in imported['partial_observations'] if row['provider_player_id'] not in full_ids]
    mappings = build_mapping_registry(observations+partial,references,manual,rejected_candidates(root))
    counts = Counter(m['status'] for m in mappings)
    played = [row for row in observations if row['participation'] == 'played']
    assessment = assess_completeness(observations,completeness_audit)
    missing = assessment['missing']
    blockers = list(quality_blockers)
    if not league:
        blockers.append('Premier League catalog identity unavailable or ambiguous')
    complete_collection = full and set(complete_listings) == set(seasons) and bool(matches) and len(completed) == len(matches)
    if not complete_collection:
        blockers.append('Complete 2021/22–2026/27 listings and match/player/event/lineup responses are not cached')
    if not observations:
        blockers.append('No complete player-stat response is available; probe summaries are not training rows')
    if partial or any(m['status'] not in {'verified','out_of_scope'} for m in mappings) or not mappings:
        blockers.append('Player identities require explicit review and dated club evidence')
    if any(row['participation'] == 'unknown' for row in observations):
        blockers.append('Some player participation is unresolved')
    # Card observations remain preserved for audit, but unsupported semantics do
    # not block a model whose feature list explicitly excludes cards.
    blockers.extend(assessment['blockers'])
    dates = sorted(str(m.get('date') or m.get('time_utc',''))[:10] for m in matches.values())
    listing_cutoff = str(listing_fetched_at.get('2026/2027',as_of))[:10]
    coverage_end = min(as_of,listing_cutoff)
    if complete_collection and listing_cutoff < as_of:
        blockers.append('Current-season listing snapshot predates the requested as-of date')
    coverage = [{'start':dates[0],'end_exclusive':coverage_end,'complete':True,'league':'GB1'}] if complete_collection else []
    histories = json.loads((root/'artifacts/history.json').read_text(encoding='utf-8'))
    targets = build_history_snapshots(histories)
    targets = targets[targets.year >= 2022].to_dict('records')
    dataset = build_pilot_rows(observations,targets,mappings,coverage)
    if not dataset['rows']:
        blockers.append('No eligible historical training rows passed identity and full-window checks')
    status = {'schema_version':1,'provider':'PitchAPI','pilot_league':'Premier League','league_code':'GB1',
        'status':'blocked' if blockers else 'ready_for_evaluation', 'ready_for_training':not blockers,
        'pilot_passed':False,'other_leagues_enabled':False,
        'continuously_live':False,'estimate_source_changed':False,
        'as_of':as_of,'probe_run_started_at':imported['probe_run_started_at'],
        'listing_snapshot_fetched_at':listing_fetched_at,
        'last_sample_match_date':dates[-1] if dates else None,
        'source_response_fetched_at':max(fetched_dates) if fetched_dates else None,
        'probe_season_evidence':imported['listing_summary'],
        'complete_player_matches':len({r['match_id'] for r in observations}),
        'sample_match_summaries':len(imported['matches']), 'partial_player_examples':len(partial),
        'normalized_player_rows':len(observations),'played_rows':len(played),
        'mapping_counts':dict(counts),'missing_played_stats':missing,
        'accepted_missing_fields':assessment['accepted_missing_fields'],
        'excluded_features':['yellow_cards','red_cards'],
        'historical_rows':len(dataset['rows']),'excluded_targets':len(dataset['excluded_targets']),
        'blockers':blockers,'missing_response_count':len(issues),'missing_responses_sample':issues[:20],
        'network_requests_this_run':client.network_requests,
        'scope':'Premier League domestic matches only; shipped estimates still use bundled historical data',
        'summary_limit':'Probe examples lack full rows and team IDs. No name-only identities were accepted.'}
    write_json(artifacts/'player_mappings.json',mappings)
    write_json(local/'normalized_appearances.json',observations)
    write_json(local/'historical_rows.json',dataset)
    if not blockers:
        try:
            evaluate_pilot(dataset['rows'],status,artifacts)
            status.update(status='pilot_evaluated',pilot_passed=True)
        except ValueError:
            status['blockers'].append('Chronological evaluation did not meet minimum sample requirements')
            status.update(status='blocked',ready_for_training=False)
    write_json(artifacts/'status.json',status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-report',type=Path)
    parser.add_argument('--online',action='store_true',help='Use environment credential for cache misses only')
    parser.add_argument('--full',action='store_true',help='Collect/validate all six pilot seasons before evaluating')
    parser.add_argument('--max-requests',type=int,default=50)
    parser.add_argument('--as-of',type=date.fromisoformat,default=date(2026,11,13))
    args = parser.parse_args()
    result = run_pilot(probe_report=args.probe_report,online=args.online,full=args.full,
                       max_requests=args.max_requests,as_of=args.as_of.isoformat())
    print(json.dumps({k:result[k] for k in ['status','pilot_league','network_requests_this_run',
        'complete_player_matches','mapping_counts','historical_rows','blockers']},indent=2))


if __name__ == '__main__':
    try:
        main()
    except SourceUnavailable as error:
        print(str(error))
        raise SystemExit(1)
    except Exception as error:
        print('Pilot stopped safely:',type(error).__name__)
        raise SystemExit(1)
