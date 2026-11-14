"""Audit already-cached samples only. Never collects or rewrites collection reports."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from touchline.pitchapi import PitchClient, SourceUnavailable, write_json
from touchline.pitchapi_data import normalize_match, assess_completeness
from touchline.pitchapi_matching import build_mapping_registry
from touchline.pitchapi_quality import audit_match
from touchline.pitchapi_review import read, rejected_candidates

ROOT = Path(__file__).resolve().parents[1]


def audit_cached(root=ROOT):
    root = Path(root)
    client = PitchClient(root/'data/pitchapi-cache', api_key='')
    paths = sorted({read(path, {}).get('path','') for path in client.cache_dir.glob('*.json')})
    mids = [path.rsplit('/',1)[-1] for path in paths if re.fullmatch(r'/v1/matches/[A-Za-z0-9_]+',path)]
    rows, matches, sources, errors = [], [], [], []
    for mid in mids:
        try:
            envelopes = {part:client.get('/v1/matches/'+mid+('/'+part if part else ''))
                         for part in ['', 'players','events','lineups']}
        except SourceUnavailable as error:
            errors.append({'match_id':mid,'code':error.code,'path':error.path})
            continue
        match = envelopes['']['data']
        normalized = normalize_match(match,envelopes['players']['data'],envelopes['events']['data'],
            fetched_at=envelopes['players']['fetched_at'],lineups=envelopes['lineups']['data'])
        rows.extend(normalized)
        quality = audit_match(match,envelopes['events']['data'],normalized)
        quality['confirmed_lineup_sides'] = [side for side in ['home','away']
            if envelopes['lineups']['data'].get(side,{}).get('confirmed') is True]
        matches.append(quality)
        sources.extend({'path':e['path'],'fetched_at':e['fetched_at'],'data_sha256':e['data_sha256'],
                        'provenance':e['provenance']} for e in envelopes.values())
    local = root/'data/pitchapi-local'
    references = read(root/'artifacts/players.json', [])
    extra = {r['player_id']:r for r in read(local/'identity_evidence.json', [])}
    references = [r | {k:v for k,v in extra.get(r['player_id'],{}).items()
                       if k in {'club_evidence','name_aliases','provider_links'}} for r in references]
    manual = read(local/'manual_mappings.json', [])
    mappings = build_mapping_registry(rows,references,manual,rejected_candidates(root))
    lookup = {r['player_id']:r for r in references}
    for mapping in mappings:
        mapping['candidates'] = [{'player_id':pid,'name':lookup[pid]['name'],
            'snapshot_club':lookup[pid].get('club'),'snapshot_date':lookup[pid].get('date'),
            'warning':'Snapshot club is not dated membership proof'} for pid in mapping['candidate_ids']]
        mapping['review_requirement'] = 'Independent crosswalk or documented full-name/alias and dated club evidence; never name alone'
    played = [r for r in rows if r['participation']=='played']
    keepers = []
    for row in played:
        evidence = sorted(k for k in row['raw_stats'] if k in
                          {'top_stats.saves','top_stats.goals_conceded','top_stats.saves_inside_box'})
        if evidence and (row['goals'] is None or row['assists'] is None):
            keepers.append({k:row[k] for k in ['provider_player_id','provider_name','match_id','date','goals','assists']}
                           | {'role_evidence_keys':evidence,'interpretation':'Keeper-specific fields observed; missing goals/assists remain null'})
    old = read(root/'artifacts/pitchapi/status.json', {})
    assessment = assess_completeness(rows,{})
    report = {'network_requests_this_audit':client.network_requests,
        'collection_requests_recorded':old.get('network_requests_this_run'),
        'complete_sample_matches':len(matches),'normalized_rows':len(rows),'played_rows':len(played),
        'mapping_counts':dict(Counter(r['status'] for r in mappings)),
        'unmatched_names':[r['provider_name'] for r in mappings if r['status']=='unmatched'],
        'match_quality':matches,'cache_errors':errors,'source_responses':sources,
        'keeper_missing_stats':keepers,'completeness':assessment,
        'ignored_empty_keys':sum(r['ignored_empty_keys'] for r in rows),
        'ready_for_full_collection':False,'ready_for_training':False,'continuously_live':False,
        'historical_rows_recorded':old.get('historical_rows'),
        'blockers':['Resolve inconsistent goal evidence without dropping records',
            'Independently verify identities or explicitly document out-of-scope decisions',
            'Document goalkeeper sparse-stat semantics; preserve null values',
            'Verify provider own-goal and second-yellow conventions on actual source examples',
            'Obtain complete dated pre-valuation match windows only after pilot approval'],
        'scope':'Cached three-match sample audit; not a new collection, full-season coverage, or model evaluation'}
    # Fingerprints let a reviewer detect stale evidence before using the queue.
    report['queue_sha256'] = hashlib.sha256(json.dumps(mappings,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    write_json(root/'artifacts/pitchapi/review_queue.json',mappings)
    write_json(root/'artifacts/pitchapi/quality_readiness.json',report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    args = parser.parse_args()
    report = audit_cached(args.root)
    print(json.dumps({k:report[k] for k in ['network_requests_this_audit','complete_sample_matches',
        'normalized_rows','mapping_counts','ready_for_full_collection','ready_for_training']},indent=2))


if __name__=='__main__':
    main()
