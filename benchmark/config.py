"""Explicit configuration and local credentials; no implicit credential discovery."""
import json
import os
import re
from urllib.parse import urlsplit
from benchmark.data import PRIMARY, SUITES

PAPER = {
    'deepseek': dict(model='deepseek-v4-pro', adapter='chat_completions', base_url='https://api.deepseek.com', api_key_env='DEEPSEEK_API_KEY', timeout_seconds=7200),
    'luna': dict(model='gpt-5.6-luna', adapter='responses', base_url='https://api.openai.com/v1', api_key_env='OPENAI_API_KEY', timeout_seconds=120),
}
FIELDS = {'name', 'paper_provider', 'model', 'adapter', 'base_url', 'api_key_env', 'parameters',
          'suites', 'prompt_variant', 'concurrency', 'timeout_seconds', 'poll_seconds',
          'poll_timeout_seconds', 'poll_window_seconds', 'accepted_models', 'allow_http'}


def load(path):
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(raw, dict) or set(raw) - FIELDS:
        raise ValueError('Unknown configuration fields; credentials belong in the env file')
    paper = raw.get('paper_provider')
    if paper is not None and paper not in PAPER:
        raise ValueError('paper_provider must be deepseek or luna')
    config = dict(name='custom', parameters={}, suites=list(PRIMARY), prompt_variant='deepseek', concurrency=1,
                  timeout_seconds=7200, poll_seconds=10, poll_timeout_seconds=60, poll_window_seconds=14400,
                  api_key_env=None, allow_http=False, accepted_models=[])
    if paper:
        config.update(PAPER[paper], prompt_variant=paper,
                      concurrency={'core72': 1, 'core_anchors': 4, 'original36': 4, 'paired24': 2, 'paired_repeats': 2, 'adds15': 2})
        for key in ('model', 'adapter', 'parameters', 'prompt_variant'):
            if key in raw and raw[key] != config[key]:
                raise ValueError('To change paper model/settings, remove paper_provider and use a custom configuration')
    config.update(raw)
    for key in ('model', 'adapter', 'base_url'):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ValueError('Missing configuration field: ' + key)
    if config['prompt_variant'] not in PAPER:
        raise ValueError('prompt_variant must be deepseek or luna')
    if not isinstance(config['suites'], list) or not config['suites'] or len(config['suites']) != len(set(config['suites'])) or set(config['suites']) - set(SUITES):
        raise ValueError('Select distinct suites listed by run_benchmark.py list')
    params = config['parameters']
    if not isinstance(params, dict) or {'model', 'messages', 'input', 'api_key', 'authorization'} & set(params):
        raise ValueError('parameters may contain generation options only')
    if params.get('stream') or params.get('n', 1) != 1 or params.get('tools') or params.get('functions'):
        raise ValueError('This benchmark uses one non-streaming answer and no tools')
    if config['api_key_env'] is not None and not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', config['api_key_env']):
        raise ValueError('api_key_env must be an environment variable name, not a key')
    if re.search(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{30,}', json.dumps(config)):
        raise ValueError('A possible credential was found in the configuration; use the env file')
    url = urlsplit(config['base_url'])
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.scheme not in ('http', 'https')):
        raise ValueError('base_url must be an HTTP(S) API base without credentials, query or fragment')
    if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1') and not config['allow_http']:
        raise ValueError('Remote HTTP requires allow_http=true; HTTPS is the default')
    conc = config['concurrency']
    values = list(conc.values()) if isinstance(conc, dict) else [conc]
    if not values or any(type(n) is not int or n < 1 for n in values):
        raise ValueError('concurrency must contain positive integers')
    for key in ('timeout_seconds', 'poll_seconds', 'poll_timeout_seconds', 'poll_window_seconds'):
        if not isinstance(config[key], (int, float)) or config[key] <= 0:
            raise ValueError(key + ' must be positive')
    if not isinstance(config['accepted_models'], list) or not all(isinstance(v, str) and v for v in config['accepted_models']):
        raise ValueError('accepted_models must be a list of returned model names')
    return config


def credential(config, env_file=None):
    name = config['api_key_env']
    if name is None:
        return ''
    values = {}
    if env_file:
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            key, sep, value = line.partition('=')
            if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key.strip()):
                raise ValueError('Env file must contain NAME=value lines')
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('\"', "'"):
                value = value[1:-1]
            values[key.strip()] = value
    key = values.get(name, os.environ.get(name, ''))
    if not key or key in ('REPLACE_LOCALLY', 'YOUR_API_KEY'):
        raise ValueError('Set ' + name + ' using --env-file or the process environment')
    return key


def model_matches(config, returned):
    return isinstance(returned, str) and any(returned.lower() == m.lower() or returned.lower().startswith(m.lower() + '-')
             for m in [config['model'], *config['accepted_models']])
