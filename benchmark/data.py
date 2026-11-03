"""Benchmark tasks and prompt templates, independent of any experiment run."""
from pathlib import Path
import copy
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
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
        raise ValueError('Unknown prompt variant')
    catalogue = read(ROOT / 'data/catalog.json')
    out = []
    for suite in suites:
        if suite not in SUITES:
            raise ValueError('Unknown suite: ' + suite)
        entries = [c for c in catalogue if c['suite'] == suite]
        if len(entries) != SUITES[suite]:
            raise ValueError('Incomplete task suite: ' + suite)
        for entry in sorted(entries, key=lambda c: c['ranks'][provider]):
            c = {k: v for k, v in entry.items() if k != 'ranks'}
            c['rank'] = entry['ranks'][provider]
            raw = (ROOT / c['task_path']).read_bytes()
            if digest(raw) != c['task_sha256']:
                raise ValueError('Task hash mismatch: ' + c['record_id'])
            template = read(ROOT / 'prompts' / (c['prompt_family'] + '_' + provider + '.json'))
            ms = copy.deepcopy(template['messages'])
            ms[template['task_suffix_message']]['content'] += raw.decode('utf-8')
            c['body'] = {**template['parameters'], template['input_field']: ms}
            if public_task(c)['record_id'] != c['public_record_id']:
                raise ValueError('Public task identity mismatch')
            out.append(c)
    return out


def select(all_cases, record_ids=None, limit=None):
    selected = all_cases
    if record_ids:
        wanted = set(record_ids)
        if wanted - {c['record_id'] for c in all_cases}:
            raise ValueError('Requested record_id is outside the selected suites')
        selected = [c for c in selected if c['record_id'] in wanted]
    if limit is not None:
        if limit < 1:
            raise ValueError('--limit must be positive')
        selected = selected[:limit]
    if not selected:
        raise ValueError('No tasks selected')
    return selected
