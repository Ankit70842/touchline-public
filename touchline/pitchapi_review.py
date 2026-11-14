"""Offline identity review. No network access; every decision keeps its provenance."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
from touchline.pitchapi import write_json

ROOT = Path(__file__).resolve().parents[1]


def read(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def rejected_candidates(root):
    latest = {}
    for item in read(Path(root)/'data/pitchapi-local/review_decisions.json', []):
        latest[(item['provider_player_id'],item.get('player_id'))] = item['action']
    result = {}
    for (provider, player), action in latest.items():
        if action=='reject' and player is not None:
            result.setdefault(provider, set()).add(player)
    return result


def review_queue(root=ROOT):
    root = Path(root)
    queue = read(root/'artifacts/pitchapi/review_queue.json', [])
    history = read(root/'data/pitchapi-local/review_decisions.json', [])
    manual = {m['provider_player_id']:m for m in read(root/'data/pitchapi-local/manual_mappings.json', [])}
    for row in queue:
        decisions = [d for d in history if d['provider_player_id']==row['provider_player_id']]
        latest = {}
        for d in decisions:
            latest[d.get('player_id')] = d['action']
        row['rejected_candidate_ids'] = sorted(pid for pid,action in latest.items() if pid is not None and action=='reject')
        row['review_history'] = decisions
        row['manual_decision'] = manual.get(row['provider_player_id'])
        row['revision'] = hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return queue


def decide(root, provider_id, action, player_id, source, reason, revision):
    root = Path(root)
    if action not in {'approve','reject','out_of_scope'} or not source.strip() or not reason.strip():
        raise ValueError('Decision requires action, independent source, and reason')
    if (action=='out_of_scope') != (player_id is None):
        raise ValueError('Approve/reject require a reference ID; out_of_scope requires no reference ID')
    local = root/'data/pitchapi-local'
    local.mkdir(parents=True, exist_ok=True)
    lock = local/'review.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('Another review is active, or a prior review was interrupted; inspect review.lock before retrying') from None
    try:
        os.close(descriptor)
        queue = {r['provider_player_id']:r for r in review_queue(root)}
        if provider_id not in queue:
            raise ValueError('Unknown provider ID; regenerate the offline queue first')
        if revision != queue[provider_id]['revision']:
            raise ValueError('Review changed since inspection; show the provider ID again before deciding')
        references = {r['player_id'] for r in read(root/'artifacts/players.json', [])}
        if player_id is not None and player_id not in references:
            raise ValueError('Reference ID does not exist')
        manual = read(local/'manual_mappings.json', [])
        if action=='approve' and any(m.get('status')=='verified' and m.get('player_id')==player_id
                and m['provider_player_id']!=provider_id for m in manual):
            raise ValueError('Reference ID already linked to another provider ID; resolve the conflict first')
        decision = {'provider_player_id':provider_id,'action':action,'player_id':player_id,
                    'source':source.strip(),'reason':reason.strip(),
                    'reviewed_at':datetime.now(timezone.utc).isoformat()}
        # The audit is written first. A crash cannot leave an unlogged approval.
        history = read(local/'review_decisions.json', [])
        write_json(local/'review_decisions.json', history+[decision])
        remaining = [m for m in manual if m['provider_player_id']!=provider_id]
        if action in {'approve','out_of_scope'}:
            remaining.append({'provider_player_id':provider_id,'player_id':player_id,
                'status':'verified' if action=='approve' else 'out_of_scope','method':'manual',
                'evidence':[decision]})
            write_json(local/'manual_mappings.json', remaining)
        elif any(m['provider_player_id']==provider_id and m.get('player_id')==player_id for m in manual):
            write_json(local/'manual_mappings.json', remaining)
        return decision
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    sub = parser.add_subparsers(dest='command',required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--status')
    listing.add_argument('--search',default='')
    listing.add_argument('--offset',type=int,default=0)
    listing.add_argument('--limit',type=int,default=20)
    show = sub.add_parser('show'); show.add_argument('provider_id')
    for action in ['approve','reject','out_of_scope']:
        child = sub.add_parser(action); child.add_argument('provider_id')
        if action!='out_of_scope':
            child.add_argument('player_id',type=int)
        child.add_argument('--source',required=True); child.add_argument('--reason',required=True)
        child.add_argument('--revision',required=True,help='Revision from the most recent show command')
    args = parser.parse_args()
    try:
        if args.command=='list':
            if args.offset<0 or not 1<=args.limit<=200:
                raise ValueError('Use offset >= 0 and limit 1..200')
            rows = [r for r in review_queue(args.root) if (not args.status or r['status']==args.status)
                    and args.search.casefold() in json.dumps(r,ensure_ascii=False).casefold()]
            output = {'total':len(rows),'rows':rows[args.offset:args.offset+args.limit]}
        elif args.command=='show':
            output = next((r for r in review_queue(args.root) if r['provider_player_id']==args.provider_id),None)
            if output is None:
                raise ValueError('Unknown provider ID')
        else:
            output = decide(args.root,args.provider_id,args.command,getattr(args,'player_id',None),args.source,args.reason,args.revision)
        print(json.dumps(output,ensure_ascii=True,indent=2))
    except ValueError as error:
        parser.exit(2,str(error)+'\n')


if __name__=='__main__':
    main()
