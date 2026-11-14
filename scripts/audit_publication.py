"""Read-only bounded secret/history inventory. Never prints matching values."""
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib


def git(*args):
    return subprocess.check_output(['git',*args])


def audit():
    objects={}
    for line in git('rev-list','--objects','--all').decode().splitlines():
        sha,_,path=line.partition(' ')
        objects.setdefault(sha,path)
    patterns={
        'provider_token':rb'(?:sk-proj-|sk-ant-)[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{35}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|(?:pk|sk)_(?:live|test)_[A-Za-z0-9]{16,}|xox[bp]-[A-Za-z0-9-]{20,}',
        'private_key':rb'-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----',
        'jwt_candidate':rb'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
        'credential_query':rb'(?i)https?://[^\s"<>]+[?&](?:api_key|access_token|password|secret)=[A-Za-z0-9_%.-]{8,}',
        'credential_url':rb'https?://[^\s/:]+:[^\s/@]+@|(?:postgres|mysql|mongodb|redis)://[^\s]+:[^\s]+@',
        'credential_assignment':rb'''(?i)(?:api_key|secret|password|access_token)\s*[=:]\s*["']([^"'\r\n]{10,})["']''',
        'personal_path':rb'(?i)[A-Z]:[\\/]+Users[\\/]|/home/[^/\s]+/|/Users/[^/\s]+/',
        'private_url':rb'https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|[^/\s]*\.internal)(?=[:/\s])',
    }
    findings=[];large=[];binaries=[];environments=[];blob_count=0
    for sha,path in objects.items():
        kind=git('cat-file','-t',sha).strip()
        if kind not in {b'blob',b'commit',b'tag'}:
            continue
        content=git('cat-file','-p',sha)
        if kind==b'blob':
            blob_count+=1
            if len(content)>1024*1024:
                large.append({'object':sha,'path':path,'bytes':len(content)})
            if path.endswith(('.joblib','.png','.zip','.sqlite','.db')):
                binaries.append({'object':sha,'path':path,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
            if re.search(r'(^|/)(\.env(?:\..*)?|[^/]+\.(?:pem|key|p12|pfx)|id_rsa)$',path):
                environments.append({'object':sha,'path':path})
        payloads=[content]
        if path.endswith('.joblib'):
            try:
                reader=zlib.decompressobj();expanded=reader.decompress(content,20*1024*1024)
                payloads.append(expanded)  # Byte inspection only; NEVER unpickle.
            except zlib.error:
                pass
        for label,pattern in patterns.items():
            hits=[]
            for data in payloads:
                hits.extend(re.finditer(pattern,data))
            if hits:
                item={'object':sha,'path':path or '<commit/tag metadata>','category':label,'count':len(hits)}
                if label=='credential_assignment':
                    item['classification']='known_test_fixture' if path.startswith('tests/') and all(
                        h.group(1) in {b'fixture-secret',b'fixture-key'} for h in hits) else 'requires_review'
                findings.append(item)
    return {'refs':git('for-each-ref','--format=%(refname)').decode().splitlines(),
        'commits':len(git('rev-list','--all').splitlines()),'unique_blobs':blob_count,
        'findings':findings,'large_objects':large,'binary_objects':binaries,'environment_or_key_paths':environments,
        'limitations':['Pattern scan is not a proof of absence; unknown/encoded secrets may evade it.',
            'Only locally reachable refs after fetch are included; deleted remote refs/server caches are not inspectable.',
            'This audit script byte-inspects models and never unpickles. It does not certify model execution safety.',
            'Loopback URLs are expected local development endpoints; generic assignments require manual classification.']}


if __name__=='__main__':
    report=audit()
    output=Path('data/publication-audit-local.json');output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['commits','unique_blobs','refs','environment_or_key_paths']},indent=2))
    print('Finding categories:',dict(collections.Counter(f['category'] for f in report['findings'])))
    print('Details saved locally; values are never printed.')
