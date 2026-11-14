"""Export the small evidenced Arsenal cohort and its missing-data plan, offline."""
from datetime import date, timedelta
from pathlib import Path
import json
import pandas as pd
from touchline.pitchapi import PitchClient, SourceUnavailable, write_json
from touchline.pitchapi_data import normalize_match, assess_completeness
from touchline.pitchapi_matching import build_mapping_registry, name_key
from touchline.pitchapi_quality import audit_match
from touchline.pitchapi_review import read
from touchline.pitchapi_training import build_pilot_rows
from touchline.valuation import attach_previous_valuations

ROOT = Path(__file__).resolve().parents[1]


def build_arsenal_pilot(root=ROOT):
    root = Path(root)
    folder = root/'artifacts/pitchapi'
    cohort = read(folder/'arsenal_cohort.json', {})
    client = PitchClient(root/'data/pitchapi-cache', api_key='')
    mid = cohort['cached_match_id']
    if mid in cohort['quarantined_match_ids']:
        raise ValueError('The selected source match is quarantined')
    bodies = [client.get('/v1/matches/'+mid+suffix) for suffix in ['', '/players','/events','/lineups']]
    detail, players, events, lineups = [body['data'] for body in bodies]
    if detail['date'] != cohort['official_report_date']:
        raise ValueError('Cached match date differs from independent membership evidence')
    if cohort['provider_team_id'] not in [detail[s]['id'] for s in ['home_team','away_team']]:
        raise ValueError('Selected club does not participate in the cached match')
    normalized = normalize_match(detail, players, events, lineups=lineups, fetched_at=bodies[1]['fetched_at'])
    quality = audit_match(detail, events, normalized)
    if not quality['passed']:
        raise ValueError('Source match failed goal-evidence checks')
    references = read(root/'artifacts/players.json', [])
    for player in cohort['players']:
        ref = next((r for r in references if r['player_id']==player['player_id']),None)
        if ref is None or name_key(ref['name']) != name_key(player['name']):
            raise ValueError('Independent profile identity differs from bundled reference')
        ref['club_evidence'] = [{'club':cohort['club'],'provider_team_id':cohort['provider_team_id'],
            'valid_from':cohort['official_report_date'],'valid_to':cohort['official_report_date'],
            'source':cohort['official_match_report'],'identity_source':player['profile_url'],
            'verified':True,'scope':'Membership established on the match date only'}]
    ids = {p['provider_player_id'] for p in cohort['players']}
    selected = [r for r in normalized if r['provider_player_id'] in ids and r['provider_team_id']==cohort['provider_team_id']]
    mappings = build_mapping_registry(selected,references)
    if len(mappings)!=len(ids) or any(m['status']!='verified' for m in mappings):
        raise ValueError('Not all selected identities have unambiguous independent support')
    expected = {p['provider_player_id']:p['player_id'] for p in cohort['players']}
    if any(m['player_id']!=expected[m['provider_player_id']] for m in mappings):
        raise ValueError('Resolved crosswalk differs from independently inspected identity')
    assessment = assess_completeness(selected,{})
    if assessment['blockers'] or any(r['participation']!='played' for r in selected):
        raise ValueError('Selected outfield source records have unsupported core statistics')
    kept = ['provider_player_id','provider_name','provider_team_id','club','match_id','date',
            'league','minutes','goals','assists','xg','xa','participation','fetched_at']
    source_rows = [{k:r.get(k) for k in kept} | {'player_id':expected[r['provider_player_id']]} for r in selected]
    histories = read(root/'artifacts/history.json', {})
    targets = []
    for player in cohort['players']:
        labels = [h for h in histories.get(str(player['player_id']),[]) if h['date']==cohort['target_date']]
        if len(labels)!=1 or labels[0]['market_value_in_eur']<=0:
            raise ValueError('Require one genuine positive label on the declared target date')
        targets.append({'player_id':player['player_id'],'date':cohort['target_date'],
                        'actual_value':labels[0]['market_value_in_eur']})
    targets = attach_previous_valuations(pd.DataFrame(targets),histories).to_dict('records')
    for target in targets:
        day = date.fromisoformat(target['date'])
        target.update(performance_window_start=(day-timedelta(days=365)).isoformat(),
            performance_window_end_exclusive=day.isoformat(),recent_window_start=(day-timedelta(days=90)).isoformat(),
            label_source='artifacts/history.json; bundled Transfermarkt-derived dated values')
    # Resolve only a complete, validated cached listing. Never turn the public
    # acquisition checklist into synthetic source matches or complete coverage.
    listing_path = '/v1/leagues/'+cohort['league_id']+'/matches'
    listing_params = {'season':cohort['season'],'status':'played'}
    matches,listing_source,listing_problem = [],None,None
    try:
        listing = client.get(listing_path,listing_params)
        from touchline.pitchapi_collect_arsenal import resolve_listing
        matches = resolve_listing(listing['data'],cohort)
        listing_source = {k:listing[k] for k in ['path','params','fetched_at','data_sha256']}
    except (SourceUnavailable,ValueError) as error:
        listing_problem = error.code if isinstance(error,SourceUnavailable) else str(error)
    match_audits=[{'match_id':mid,'date':detail['date'],'passed':True,'blockers':[]}]
    absence_evidence,extra_sources = [],[]
    failed_players = set()
    player_issues=[]
    for match in matches:
        if match['id']==mid:
            continue
        try:
            more = [client.get('/v1/matches/'+match['id']+suffix) for suffix in ['/players','/events','/lineups']]
            normalized_more = normalize_match(match,more[0]['data'],more[1]['data'],lineups=more[2]['data'],fetched_at=more[0]['fetched_at'])
            check = audit_match(match,more[1]['data'],normalized_more)
            extra_sources.extend({k:b[k] for k in ['path','fetched_at','data_sha256']} for b in more)
            match_audits.append({k:check[k] for k in ['match_id','date','passed','blockers','own_goal_beneficiary_evidence']})
            if not check['passed']:
                failed_players.update(expected.values()); continue
            side = 'home' if match['home_team']['id']==cohort['provider_team_id'] else 'away'
            roster = more[2]['data'].get(side,{})
            roster_ids = {p['player_id'] for p in roster.get('starters',[])+roster.get('subs',[]) if p.get('player_id')}
            by_id = {r['provider_player_id']:r for r in normalized_more}
            for player in cohort['players']:
                pid=player['provider_player_id']; row=by_id.get(pid)
                if row is None:
                    if roster.get('confirmed') is True and len(roster.get('starters',[]))==11 and pid not in roster_ids:
                        absence_evidence.append({'player_id':player['player_id'],'match_id':match['id'],
                            'date':match['date'],'reason':'Not in confirmed Arsenal matchday squad; no appearance row invented'})
                    else:
                        failed_players.add(player['player_id'])
                        player_issues.append({'player_id':player['player_id'],'match_id':match['id'],
                            'reason':'Missing player stats without complete confirmed-squad absence evidence'})
                    continue
                tokens = name_key(row['provider_name']).split(); full=name_key(player['name']).split()
                compatible = tokens==full or (tokens and full and tokens[-1]==full[-1] and tokens[0]==full[0][0])
                if row['provider_team_id']!=cohort['provider_team_id'] or not compatible or row['participation']=='unknown':
                    failed_players.add(player['player_id'])
                    player_issues.append({'player_id':player['player_id'],'match_id':match['id'],
                        'reason':'Selected player identity, team or participation is unresolved'})
                    continue
                source_rows.append({k:row.get(k) for k in kept}|{'player_id':player['player_id']})
                if row['participation']=='played' and any(row.get(k) is None for k in ['minutes','goals','assists']):
                    failed_players.add(player['player_id'])
                    player_issues.append({'player_id':player['player_id'],'match_id':match['id'],
                        'reason':'Missing core played-player statistics',
                        'fields':[k for k in ['minutes','goals','assists'] if row.get(k) is None]})
        except (SourceUnavailable,ValueError,TypeError,KeyError) as error:
            failed_players.update(expected.values())
            match_audits.append({'match_id':match['id'],'date':match['date'],'passed':False,
                'blockers':[error.code if isinstance(error,SourceUnavailable) else type(error).__name__]})
    player_checks=[]
    for player in cohort['players']:
        observed=sum(r['player_id']==player['player_id'] and r['participation']=='played' for r in source_rows)
        expected_count=player.get('expected_league_appearances')
        agrees=expected_count is None or observed==expected_count
        player_checks.append({'player_id':player['player_id'],'observed_appearances':observed,
            'expected_season_appearances':expected_count,'source':player.get('season_membership_source'),
            'complete_listing_checked':bool(matches),'agrees':agrees if matches else None})
        if matches and not agrees:
            failed_players.add(player['player_id'])
            player_issues.append({'player_id':player['player_id'],'reason':'Season appearance count differs from independent evidence',
                'observed':observed,'expected':expected_count})
    coverage=[]
    if matches and len(match_audits)==len(matches):
        eligible_ids = sorted(set(expected.values())-failed_players)
        if eligible_ids:
            coverage=[{'start':targets[0]['performance_window_start'],'end_exclusive':cohort['target_date'],
                'complete':True,'league':'GB1','player_ids':eligible_ids,
                'scope':'Arsenal Premier League appearances only; cups and international appearances excluded'}]
    dataset = build_pilot_rows(source_rows,targets,mappings,coverage,cohort_player_ids=set(expected.values()))
    for exclusion in dataset['excluded_targets']:
        exclusion['player_quality_issues']=[i for i in player_issues if i['player_id']==exclusion['player_id']]
        exclusion['match_quality_issues']=[m for m in match_audits if not m['passed']]
    by_date={m['date']:m for m in matches}
    missing=[]
    cached_sets=1 if not matches else 0
    for d,opponent,venue in cohort['fixtures']:
        candidate=by_date.get(d) or (detail if d==detail['date'] else None)
        suffixes=[s for s in ['/players','/events','/lineups'] if candidate is None or
                  not client.cache_path('/v1/matches/'+candidate['id']+s).exists()]
        if matches and not suffixes:
            cached_sets+=1
        if suffixes:
            missing.append({'date':d,'opponent':opponent,'venue':venue,
                'provider_match_id':candidate['id'] if candidate else None,'missing_suffixes':suffixes})
    listing_missing = not client.cache_path(listing_path,listing_params).exists()
    report = {'club':cohort['club'],'scope':'Selected Arsenal Premier League appearances only; cups and internationals excluded; never all-competition totals',
        'network_requests':client.network_requests,'verified_players':len(mappings),'verified_source_rows':len(source_rows),
        'eligible_training_rows':len(dataset['rows']),'source_rows':source_rows,'mappings':mappings,
        'targets':targets,'training_rows':dataset['rows'],'excluded_targets':dataset['excluded_targets'],
        'excluded_features':['yellow_cards','red_cards'],'quarantined_match_ids':cohort['quarantined_match_ids'],
        'cached_records':[{'path':b['path'],'fetched_at':b['fetched_at'],'data_sha256':b['data_sha256']} for b in bodies]+extra_sources,
        'listing_source':listing_source,'listing_problem':listing_problem,'match_audits':match_audits,
        'absence_evidence':absence_evidence,'coverage':coverage,'failed_player_ids':sorted(failed_players),
        'player_season_checks':player_checks,
        'player_quality_issues':player_issues,
        'request_plan':{'coverage':cohort['season']+' Arsenal Premier League matches only',
            'expected_matches':len(cohort['fixtures']),'cached_matches':cached_sets,
            'listing':{'path':listing_path,'params':listing_params,'missing':listing_missing},
            'missing_match_records':missing,'recommended_requests':int(listing_missing)+sum(len(m['missing_suffixes']) for m in missing),
            'minimum_players_only_requests':int(listing_missing)+len(missing),
            'minimum_limitation':'Players-only budget assumes listing has sufficient match metadata and does not validate goals/lineups; not the recommended quality plan',
            'assumptions':['One documented unpaginated season listing; verify exact fixtures and reject advertised continuation',
                'Listing supplies sufficient detail metadata; only players, events and lineups are fetched per missing match',
                'Provider IDs for the missing fixtures are unknown until the listing is obtained',
                'Inspect listing and verify club membership across the full window before any batch',
                'Required bodies may still contain missing fields or unresolved goal evidence; requests do not guarantee eligible rows']},
        'limitations':['Source match records are distinct from complete league-window training rows',
            'Independent club evidence establishes the cached match date, not a continuous season interval',
            'Dated labels lack original publication timestamps; historical availability cannot be proven',
            'Three eventual target rows cannot support chronological model selection, calibration and testing']}
    report['collection']=read(folder/'arsenal_collection.json',{'status':'not_started','requests_used':0})
    report['played_source_rows']=sum(r['participation']=='played' for r in source_rows)
    report['expansion_estimate']={'scope':'Five complete Premier League seasons 2021/22–2025/26, before retries',
        'matches':1900,'listing_requests':5,'match_body_requests':5700,'gross_requests':5705,
        'from_current_initial_cache':5702,'after_complete_Arsenal_pilot':5590,
        'assumptions':'380 matches per season, three bodies per match, five season listings; no optional analytics or repeated match-detail fetches',
        'limitations':'Identity verification, missing data and dated label availability determine usable sample size; no guaranteed row count. Use a broad cohort and chronological 2022/23 train, 2024 validation, 2025 calibration, 2026 test; do not tune against the test.'}
    write_json(folder/'arsenal_pilot.json',report)
    return report


if __name__=='__main__':
    report = build_arsenal_pilot()
    print(json.dumps({k:report[k] for k in ['network_requests','verified_players','verified_source_rows','eligible_training_rows']}
        | {'estimated_requests':report['request_plan']['recommended_requests']},indent=2))
