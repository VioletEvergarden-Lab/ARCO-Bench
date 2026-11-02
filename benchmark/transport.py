"""Durable single submissions; accepted async responses resume by GET only."""
from datetime import datetime, timezone
from pathlib import Path
import base64
import json
import time
import urllib.error
import urllib.request
from benchmark import adapters
from benchmark.config import model_matches
from benchmark.data import canonical, digest, read
from benchmark.storage import write

PENDING = {'queued', 'in_progress'}
MODEL_OUTPUT = {'completed', 'truncated', 'refused', 'incomplete'}


def utc():
    return datetime.now(timezone.utc).isoformat()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http(method, url, key, adapter, body, timeout):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', **adapter.headers(key)}
    req = urllib.request.Request(url, data=canonical(body) if body is not None else None, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        # Operational failures are not candidate answers. Do not copy an error
        # page (which can echo request credentials) into scientific output.
        meta = {'http_status': exc.code, 'error': 'http_error'}
        try:
            error = json.loads(exc.read()).get('error')
            fields = error if isinstance(error, dict) else {'message': error}
            for name in ('code', 'type', 'message'):
                if isinstance(fields.get(name), (str, int)):
                    value = str(fields[name])
                    if key:
                        for secret in (key, json.dumps(key)[1:-1], base64.b64encode(key.encode()).decode()):
                            value = value.replace(secret, '[REDACTED]')
                    meta['provider_error_' + name] = value[:1500]
        except (ValueError, AttributeError, OSError):
            pass
        return meta, None
    except Exception as exc:
        return {'http_status': None, 'error': type(exc).__name__}, None
    if key:
        variants = [key.encode(), json.dumps(key)[1:-1].encode(), base64.b64encode(key.encode())]
        if any(v in raw for v in variants):
            return {'http_status': status, 'error': 'credential_echo_rejected'}, None
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError()
        canonical(obj)  # Reject non-finite numbers accepted by Python's JSON decoder.
    except (ValueError, UnicodeError):
        return {'http_status': status, 'error': 'invalid_json_envelope'}, None
    return {'http_status': status}, obj


def attempt(case, config, root, key, worker):
    start = time.perf_counter(); wall_start = time.time()
    folder = root / 'attempts' / case['attempt_id']; folder.mkdir(parents=True, exist_ok=True)
    result_path = folder / 'result.json'
    if result_path.exists() and read(result_path)['status'] != 'pending':
        return read(result_path)
    adapter = adapters.load(config['adapter'])
    request = read(root / 'requests' / (case['attempt_id'] + '.json'))
    intent_path = folder / 'submission.json'
    resumed = intent_path.exists()
    if not resumed:
        write(intent_path, {'started_utc': datetime.fromtimestamp(wall_start, timezone.utc).isoformat(),
                            'request_sha256': digest(canonical(request)), 'post_intents': 1}, immutable=True)
    intent = read(intent_path)
    if intent['request_sha256'] != digest(canonical(request)):
        raise ValueError('Prepared request changed after submission')
    elapsed_before = max(0., wall_start - datetime.fromisoformat(intent['started_utc']).timestamp()) if resumed else 0.
    record = dict(attempt_id=case['attempt_id'], record_id=case['record_id'], suite=case['suite'], repeat=case['repeat'],
                  requested_model=config['model'], raw_text='', returned_model=None, source='live',
                  resumed=resumed, response_seconds=None, available_seconds=None)

    def finish(status, **fields):
        record.update(status=status, **fields)
        write(result_path, record)
        return record

    def parse(obj):
        try:
            state = adapter.parse(obj)
            if not isinstance(state, adapters.Completion) or not isinstance(state.text, str):
                raise ValueError()
            return state
        except (TypeError, ValueError, KeyError, AttributeError, IndexError):
            return adapters.Completion(status='invalid_envelope')

    accepted = folder / 'accepted.json'
    saved = folder / 'provider_response.json'
    if saved.exists():
        state = parse(read(saved))
    elif accepted.exists():
        state = adapters.Completion(status='in_progress', response_id=read(accepted)['response_id'])
    elif resumed:
        return finish('uncertain_submission', error='A prior POST may have reached the server; it will not be repeated')
    else:
        meta, obj = http('POST', config['base_url'].rstrip('/') + request['path'], key, adapter,
                         request['body'], config['timeout_seconds'])
        write(folder / 'post.json', {**meta, 'response_seconds': time.perf_counter() - start}, immutable=True)
        if obj is None:
            return finish('request_failed' if meta['http_status'] is not None else 'uncertain_submission', **meta)
        write(saved, obj)
        state = parse(obj)
    if state.status in PENDING:
        if not state.response_id or not adapter.poll_path(state.response_id):
            return finish('invalid_envelope', error='Async response has no pollable ID')
        if not accepted.exists():
            write(accepted, {'response_id': state.response_id}, immutable=True)
        response_id = read(accepted)['response_id']
        deadline = time.monotonic() + config['poll_window_seconds']
        while state.status in PENDING:
            if time.monotonic() >= deadline:
                return finish('pending', response_id=response_id)
            time.sleep(config['poll_seconds'])
            meta, obj = http('GET', config['base_url'].rstrip('/') + adapter.poll_path(response_id), key, adapter,
                             None, config['poll_timeout_seconds'])
            if obj is None:
                # Keep the accepted ID for a later --resume, without another POST.
                return finish('pending', response_id=response_id, **meta)
            state = parse(obj)
            if state.response_id != response_id:
                return finish('invalid_envelope', error='Poll response ID changed')
            write(saved, obj)
    record.update(raw_text=state.text, returned_model=state.model, usage=state.usage,
                  provider_status=state.status, response_id=state.response_id,
                  response_seconds=elapsed_before + time.perf_counter() - start)
    if state.status == 'invalid_envelope':
        return finish('invalid_envelope')
    if state.status not in MODEL_OUTPUT:
        return finish('provider_failed')
    if not model_matches(config, state.model):
        return finish('model_mismatch')
    if state.tool_call:
        return finish('refused', error='Tool calls are outside this benchmark protocol')
    if state.status == 'completed':
        public = worker.call('validate', case, state.text)
        record['public_verification'] = public
    record['available_seconds'] = elapsed_before + time.perf_counter() - start
    return finish(state.status)
