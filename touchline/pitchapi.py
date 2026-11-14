"""Read-only, cache-first PitchAPI boundary. Credentials never enter artifacts."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import httpx

BASE_URL = 'https://api.pitchapi.dev'


class SourceUnavailable(RuntimeError):
    def __init__(self, code, path, status=None, retry_after=None):
        self.code, self.path, self.status, self.retry_after = code, path, status, retry_after
        super().__init__(f'{code}: {path}' + (f' (HTTP {status})' if status else ''))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     suffix='.tmp', delete=False) as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        temporary = Path(output.name)
    temporary.replace(path)


class PitchClient:
    def __init__(self, cache_dir, api_key=None, transport=None):
        self.cache_dir = Path(cache_dir)
        self.api_key = api_key if api_key is not None else os.environ.get('PITCHAPI_API_KEY', '')
        self.transport = transport
        self.network_requests = 0

    def cache_path(self, path, params=None):
        if self.api_key and self.api_key in path:
            raise ValueError('Credentials cannot be request paths')
        if not re.fullmatch(r'/v1/[A-Za-z0-9_/-]+', path) or '..' in path:
            raise ValueError('Only relative PitchAPI v1 paths are allowed')
        if set(params or {}) - {'season','status'}:
            raise ValueError('Only documented season/status query parameters are accepted')
        if self.api_key and any(self.api_key in str(value) for value in (params or {}).values()):
            raise ValueError('Credentials cannot be query parameters')
        identity = json.dumps([path, params or {}], sort_keys=True)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return self.cache_dir / (digest+'.json')

    def seed(self, path, data, *, params=None, fetched_at=None, provenance='network'):
        destination = self.cache_path(path, params)
        serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if self.api_key and self.api_key in serialized:
            raise SourceUnavailable('CREDENTIAL_ECHO_REJECTED', path)
        envelope = {'path': path, 'params': params or {}, 'data': data,
            'fetched_at': fetched_at or datetime.now(timezone.utc).isoformat(),
            'provenance': provenance, 'complete_response': True,
            'data_sha256': hashlib.sha256(serialized.encode()).hexdigest()}
        if not destination.exists():
            write_json(destination, envelope)
        return json.loads(destination.read_text(encoding='utf-8'))

    def get(self, path, params=None, *, online=False, optional=False):
        destination = self.cache_path(path, params)
        if destination.exists():
            envelope = json.loads(destination.read_text(encoding='utf-8'))
            if envelope.get('complete_response') is not True:
                raise SourceUnavailable('PARTIAL_RESPONSE_REJECTED', path)
            serialized = json.dumps(envelope['data'], ensure_ascii=False, sort_keys=True, allow_nan=False)
            if envelope.get('data_sha256') != hashlib.sha256(serialized.encode()).hexdigest():
                raise SourceUnavailable('CACHE_INTEGRITY_FAILURE', path)
            return envelope
        if not online:
            raise SourceUnavailable('OFFLINE_CACHE_MISS', path)
        if not self.api_key:
            raise SourceUnavailable('API_KEY_NOT_VISIBLE', path)
        # Never follow a redirect carrying the credential to another destination.
        with httpx.Client(base_url=BASE_URL, headers={'X-API-KEY': self.api_key},
                          transport=self.transport, timeout=30, follow_redirects=False) as client:
            self.network_requests += 1
            try:
                response = client.get(path, params=params)
            except httpx.HTTPError as error:
                raise SourceUnavailable(type(error).__name__, path) from None
        try:
            body = response.json()
        except ValueError:
            raise SourceUnavailable('NON_JSON_RESPONSE', path, response.status_code) from None
        if not response.is_success:
            error = body.get('error', {}) if isinstance(body, dict) else {}
            code = error.get('code', 'HTTP_ERROR') if isinstance(error, dict) else 'HTTP_ERROR'
            # Use only a known error code, never an arbitrary provider message.
            code = code if code in {'UNAUTHORIZED','RATE_LIMIT_EXCEEDED','INVALID_PARAMETER',
                'RESOURCE_NOT_FOUND','ANALYTICS_UNAVAILABLE','HALVES_UNAVAILABLE',
                'INTERNAL_SERVER_ERROR','HTTP_ERROR'} else 'HTTP_ERROR'
            if optional and response.status_code == 404 and code == 'ANALYTICS_UNAVAILABLE':
                return {'data': None, 'available': False, 'reason': code, 'path': path}
            delay = response.headers.get('Retry-After')
            try:
                delay = max(0,float(delay)) if delay is not None else None
            except ValueError:
                try:
                    retry_date = parsedate_to_datetime(delay)
                    delay = max(0,(retry_date-datetime.now(timezone.utc)).total_seconds())
                except (TypeError,ValueError,OverflowError):
                    delay = None
            raise SourceUnavailable(code, path, response.status_code, retry_after=delay)
        if not isinstance(body, dict) or 'data' not in body:
            raise SourceUnavailable('INVALID_ENVELOPE', path, response.status_code)
        # Do not discard pagination outside `data` when unwrapping the response.
        for container in [body,body.get('pagination',{}),body.get('meta',{}),body.get('links',{})]:
            if isinstance(container,dict) and (any(container.get(k) for k in ['next','next_page','next_cursor','has_more'])
                    or container.get('total_pages',1)!=1):
                raise SourceUnavailable('UNSUPPORTED_PAGINATION',path,response.status_code)
        return self.seed(path, body['data'], params=params)
