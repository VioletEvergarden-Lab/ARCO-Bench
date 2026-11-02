"""Public requests and archived responses. References are opened only by evaluators."""
from pathlib import Path
import copy
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'studies/arco_closing_study'
PAIRED = ROOT / 'studies/arco_focused_revision_20261002'
ADDS = ROOT / 'studies/arco_adds_external_20261024'
SUITES = {'core72': 72, 'original36': 36, 'paired24': 24, 'adds15': 15,
          'paired_repeats': 24, 'core_anchors': 12}
PRIMARY = ('core72', 'original36', 'paired24', 'adds15')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def messages(body):
    return copy.deepcopy(body.get('messages', body.get('input')))


def public_task(case):
    user = next(m['content'] for m in reversed(messages(case['body'])) if m['role'] == 'user')
    return json.loads(user.rsplit('Public task:', 1)[1].strip())


def cases(suites=PRIMARY, provider='deepseek'):
    if provider not in ('deepseek', 'luna'):
        raise ValueError('Unknown archived prompt variant')
    out = []
    for suite in suites:
        if suite not in SUITES:
            raise ValueError('Unknown suite: ' + suite)
        if suite == 'core72':
            bindings = read(ROOT / f'provenance/complete_public/{provider}/BINDINGS.json')
        elif suite in ('original36', 'core_anchors'):
            bindings = [b for b in read(OLD / 'online/BINDINGS.json') if b['provider'] == provider
                        and (b['layer'] == 'network') == (suite == 'original36')]
        elif suite in ('paired24', 'paired_repeats'):
            bindings = [b for b in read(PAIRED / 'online/new_generation/BINDINGS.json')
                        if b['provider'] == provider and (b['repeat'] == 1) == (suite == 'paired24')]
        else:
            original = read(ADDS / 'runs/generation/BINDINGS.json')
            effective = read(ADDS / 'runs/generation/EFFECTIVE_BINDINGS.json')
            before = {b['rank']: b for b in original}
            if len(effective) != len(original) or len({b['rank'] for b in effective}) != len(original):
                raise ValueError('Effective response bindings are incomplete')
            for b in effective:
                old = before[b['rank']]
                stripped = {k: v for k, v in b.items() if k not in
                            ('logical_attempt_id', 'replaces_operational_attempt', 'replacement_request_sha256')}
                if b['attempt_id'] != old['attempt_id']:
                    if b['attempt_id'] != old['attempt_id'] + '__transport2' or b.get('logical_attempt_id') != old['attempt_id']:
                        raise ValueError('Invalid effective response identity')
                    stripped['attempt_id'] = old['attempt_id']
                if stripped != old:
                    raise ValueError('Effective response changed the frozen task or request')
            bindings = [b for b in effective if b['provider'] == provider]
        if len(bindings) != SUITES[suite]:
            raise ValueError('Archived suite is incomplete: ' + suite)
        for b in sorted(bindings, key=lambda x: x['rank']):
            rid = b['record_id']
            if suite == 'core72':
                request = ROOT / 'provenance/complete_public' / b['request_path']
                terminal = None
            elif suite in ('original36', 'core_anchors'):
                request = OLD / 'online' / b['request_path']
                terminal = OLD / 'online' / provider / 'attempts' / rid / 'TERMINAL.json'
            elif suite in ('paired24', 'paired_repeats'):
                request = PAIRED / Path(b['request_path'].replace('\\', '/'))
                terminal = PAIRED / 'online/new_generation/attempts' / b['attempt_id'] / 'TERMINAL.json'
            else:
                request = ADDS / b['request_path']
                terminal = ADDS / 'runs/generation/attempts' / b['attempt_id'] / 'TERMINAL.json'
            raw = request.read_bytes()
            if digest(raw) != b['request_sha256']:
                raise ValueError('Frozen request hash mismatch: ' + rid)
            repeat = b.get('repeat', 1)
            case = dict(suite=suite, record_id=rid, public_record_id=b.get('public_record_id', rid),
                        repeat=repeat, rank=b['rank'], attempt_id=f'{suite}__{rid}__r{repeat}',
                        archived_request=request.relative_to(ROOT).as_posix(),
                        archived_request_sha256=b['request_sha256'], body=json.loads(raw),
                        archived_terminal=terminal.relative_to(ROOT).as_posix() if terminal else None)
            if public_task(case)['record_id'] != case['public_record_id']:
                raise ValueError('Public task identity mismatch')
            out.append(case)
    return out


def select(all_cases, record_ids=None, limit=None):
    selected = all_cases
    if record_ids:
        wanted = set(record_ids)
        known = {c['record_id'] for c in all_cases}
        if wanted - known:
            raise ValueError('Requested record_id is outside the selected suites')
        selected = [c for c in selected if c['record_id'] in wanted]
    if limit is not None:
        if limit < 1:
            raise ValueError('--limit must be positive')
        selected = selected[:limit]
    if not selected:
        raise ValueError('No tasks selected')
    return selected


def archived_outputs(selected, provider):
    core = {r['record_id']: r for r in (json.loads(s) for s in
            (ROOT / f'responses/{provider}_complete.jsonl').read_text(encoding='utf-8-sig').splitlines() if s)}
    out = []
    for c in selected:
        row = core[c['record_id']] if c['suite'] == 'core72' else read(ROOT / c['archived_terminal'])
        text = row.get('raw_text') or ''
        usable = row.get('usable_text', row.get('terminal_usable', bool(text)))
        out.append(dict(attempt_id=c['attempt_id'], record_id=c['record_id'], suite=c['suite'],
                        repeat=c['repeat'], raw_text=text, status='completed' if usable else 'no_saved_output',
                        returned_model=row.get('returned_model'), response_seconds=row.get('response_seconds', row.get('latency_seconds')),
                        available_seconds=row.get('available_seconds'), source='archived'))
    return out
