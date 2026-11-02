"""Unified preparation, generation, scoring and saved-output replay."""
import argparse
import collections
import concurrent.futures
import copy
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from benchmark import adapters
from benchmark.config import credential, load as load_config
from benchmark.data import ROOT, PRIMARY, SUITES, archived_outputs, canonical, cases, digest, messages, read, select
from benchmark.evaluate import Worker
from benchmark.storage import jsonl, output_path, run_lock, table, write
from benchmark.transport import MODEL_OUTPUT, attempt


def selected_cases(config, args):
    suites = args.suite or config['suites']
    if suites == ['all']:
        suites = list(PRIMARY)
    config['suites'] = suites
    return select(cases(suites, config['prompt_variant']), args.record_id, args.limit)


def request(case, config, adapter):
    if config.get('paper_provider'):
        body = copy.deepcopy(case['body'])
        path = '/chat/completions' if config['adapter'] == 'chat_completions' else '/responses'
    else:
        path, body = adapter.build(messages(case['body']), config)
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or '#' in path:
        raise ValueError('Adapter request path must be relative to base_url')
    if any(k.lower().replace('-', '_') in ('api_key', 'key', 'token', 'access_token') for k, _ in parse_qsl(urlsplit(path).query)):
        raise ValueError('Adapter credentials belong in headers, not the request URL')
    if not isinstance(body, dict):
        raise ValueError('Adapter request body must be a JSON object')
    return {'path': path, 'body': body}


def prepare(config, selected, output, resume=False):
    output = output_path(output)
    adapter = adapters.load(config['adapter'])
    inputs = [(c, request(c, config, adapter)) for c in selected]
    entries = [{k: v for k, v in c.items() if k not in ('body', 'archived_terminal')} |
               {'prepared_request_sha256': digest(canonical(req))} for c, req in inputs]
    manifest = dict(format_version=1, config=config, config_sha256=digest(canonical(config)), cases=entries,
                    suite_counts=dict(collections.Counter(c['suite'] for c in selected)),
                    planned_attempts=len(selected), requests_contain_references=False)
    if output.exists():
        if not (output / 'run.json').is_file() or read(output / 'run.json') != manifest:
            raise ValueError('Output exists with different inputs; choose a new run directory')
        if (output / 'attempts').exists() and not resume:
            raise ValueError('Run already started; use --resume or choose a new directory')
        for c, req in inputs:
            if read(output / 'requests' / (c['attempt_id'] + '.json')) != req:
                raise ValueError('Prepared request was modified')
    else:
        output.mkdir(parents=True)
        for c, req in inputs:
            write(output / 'requests' / (c['attempt_id'] + '.json'), req, immutable=True)
        write(output / 'run.json', manifest, immutable=True)
    return output


def missing(case):
    return {k: case[k] for k in ('attempt_id', 'record_id', 'suite', 'repeat')} | {'status': 'not_run', 'raw_text': ''}


def summaries(rows, config, mode):
    groups = {}
    for suite in dict.fromkeys(r['suite'] for r in rows):
        rs = [r for r in rows if r['suite'] == suite]
        evaluated = [r for r in rs if r['status'] in MODEL_OUTPUT]
        rq = sum(r['reference_quality'] is True for r in evaluated)
        complete = len(evaluated) == len(rs)
        timed = [r for r in evaluated if r.get('available_seconds') is not None]
        groups[suite] = dict(planned_attempts=len(rs), evaluated_outputs=len(evaluated),
                             operational_or_missing=len(rs) - len(evaluated),
                             schema_valid=sum(r['schema_valid'] for r in evaluated),
                             admissible=sum(r['admissible'] for r in evaluated), reference_quality=rq,
                             reference_quality_rate=rq / len(rs) if complete else None,
                             metrics_complete=complete,
                             selected_reference_quality=sum(r['selection']['reference_quality'] is True for r in rs),
                             availability_records=len(timed),
                             reference_quality_within_600s=sum(r['reference_quality'] is True and
                                 r['available_seconds'] <= 600 for r in timed) if timed else None,
                             statuses=dict(collections.Counter(r['status'] for r in rs)))
    return dict(mode=mode, model=config['model'], prompt_variant=config['prompt_variant'],
                planned_attempts=len(rows), groups=groups,
                metric_denominator='All planned attempts in a suite, only when each has a model output; otherwise rate is null.',
                selection='Public verifier and lexicographic comparison of the saved greedy plan and the new candidate; ties keep greedy.',
                availability='Request preparation through response parsing and public validation; resumed attempts include interruption time.',
                optimizer_calls=0)


def score_records(config, selected, records, output, mode):
    indexed = {r['attempt_id']: r for r in records}
    if len(indexed) != len(records) or set(indexed) - {c['attempt_id'] for c in selected}:
        raise ValueError('Duplicate or unknown attempt_id in responses')
    workers = {}; scored = []; flat = []; exported = []; failures = []
    try:
        for c in selected:
            rec = indexed.get(c['attempt_id'], missing(c))
            suite = c['suite']
            if suite not in workers:
                workers[suite] = Worker(suite, config['prompt_variant'])
            eligible = rec['status'] == 'completed'
            result = workers[suite].call('score', c, rec.get('raw_text', ''), eligible=eligible)
            if eligible and rec.get('public_verification') and rec['public_verification'] != {k: result[k] for k in rec['public_verification']}:
                raise RuntimeError('Online/offline public verification mismatch')
            row = {k: c[k] for k in ('attempt_id', 'record_id', 'public_record_id', 'suite', 'repeat')}
            row.update({k: rec.get(k) for k in ('status', 'returned_model', 'response_seconds', 'available_seconds', 'usage')})
            row.update(result)
            if rec['status'] not in MODEL_OUTPUT:
                # Requests with no model output remain operational records and
                # never become an invalid/infeasible model answer.
                row['reference_quality'] = None
                failures.append({k: rec.get(k) for k in ('attempt_id', 'suite', 'record_id', 'status', 'http_status', 'error',
                    'provider_error_code', 'provider_error_type', 'provider_error_message', 'response_id')})
            else:
                exported.append({k: rec.get(k) for k in ('attempt_id', 'suite', 'record_id', 'repeat', 'raw_text', 'status', 'returned_model', 'response_seconds', 'available_seconds')})
            scored.append(row)
            flat.append({k: v for k, v in row.items() if k not in ('verification', 'selection')} |
                        {'selected_source': row['selection']['source'], 'selected_reference_quality': row['selection']['reference_quality']})
    finally:
        for worker in workers.values():
            worker.close()
    summary = summaries(scored, config, mode)
    summary['generation_post_intents'] = len(list((output / 'attempts').glob('*/submission.json')))
    summary['network_calls_during_scoring'] = 0
    jsonl(output / 'responses.jsonl', exported)
    jsonl(output / 'request_status.jsonl', failures)
    jsonl(output / 'scored.jsonl', scored)
    table(output / 'results.csv', flat)
    write(output / 'summary.json', summary)
    print(json.dumps({'output': str(output), 'summary': summary}, ensure_ascii=False, indent=2))
    return summary


def run(config, selected, output, key):
    stop = False
    for suite in dict.fromkeys(c['suite'] for c in selected):
        if stop:
            break
        subset = [c for c in selected if c['suite'] == suite]
        worker = Worker(suite, config['prompt_variant'])
        concurrency = config['concurrency'].get(suite, 1) if isinstance(config['concurrency'], dict) else config['concurrency']
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                for i in range(0, len(subset), concurrency):
                    jobs = [(c, pool.submit(attempt, c, config, output, key, worker)) for c in subset[i:i+concurrency]]
                    for c, future in jobs:
                        result = future.result()
                        print(json.dumps({'attempt_id': c['attempt_id'], 'status': result['status']}), flush=True)
                        if result['status'] not in MODEL_OUTPUT:
                            stop = True
                    if stop:
                        break
        finally:
            worker.close()
    records = []
    for c in selected:
        path = output / 'attempts' / c['attempt_id'] / 'result.json'
        records.append(read(path) if path.exists() else missing(c))
    score_records(config, selected, records, output, 'new_generation')
    return 2 if stop else 0


def import_records(path, selected):
    by_aid = {c['attempt_id']: c for c in selected}
    records = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not isinstance(r, dict) or not isinstance(r.get('raw_text'), str):
            raise ValueError('Each response row needs record_id/attempt_id and string raw_text')
        if r.get('attempt_id'):
            c = by_aid.get(r['attempt_id'])
            if c is None:
                raise ValueError('Unknown attempt_id in imported responses')
        else:
            matches = [c for c in selected if c['record_id'] == r.get('record_id') and
                       ('suite' not in r or c['suite'] == r['suite']) and ('repeat' not in r or c['repeat'] == r['repeat'])]
            if len(matches) != 1:
                raise ValueError('Ambiguous or unknown record_id; include attempt_id from run.json')
            c = matches[0]
        status = r.get('status', 'completed')
        if status not in MODEL_OUTPUT:
            raise ValueError('Import model outputs only; request failures are separate operational records')
        records.append(r | {k: c[k] for k in ('attempt_id', 'record_id', 'suite', 'repeat')} | {'status': status})
    if len({r['attempt_id'] for r in records}) != len(records):
        raise ValueError('Duplicate imported response')
    return records


def parser():
    p = argparse.ArgumentParser(description='Run, score or replay ARCO-Bench with one model configuration.')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='List available task suites')
    for name in ('prepare', 'run', 'score', 'replay'):
        q = sub.add_parser(name)
        q.add_argument('--config', type=Path, required=name != 'replay')
        q.add_argument('--output', type=Path, required=True)
        q.add_argument('--suite', nargs='+', choices=[*SUITES, 'all'])
        q.add_argument('--record-id', action='append')
        q.add_argument('--limit', type=int, help='Limit requests for a small first run; recorded in run.json')
        if name == 'run':
            q.add_argument('--env-file', type=Path)
            q.add_argument('--resume', action='store_true')
        if name == 'score':
            q.add_argument('--responses', type=Path, required=True)
        if name == 'replay':
            q.add_argument('--provider', choices=['deepseek', 'luna'], default='luna')
            q.add_argument('--checks', action='store_true', help='Also run all eight saved-study diagnostic checks')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'list':
        print(json.dumps({'primary_suites': list(PRIMARY), 'suites': SUITES}, indent=2)); return 0
    config = load_config(args.config or ROOT / 'configs' / ('paper_' + args.provider + '.json'))
    selected = selected_cases(config, args)
    if args.command == 'run':
        if 'YOUR_' in config['model'] or 'YOUR_' in config['base_url']:
            raise ValueError('Replace the example model and base_url before running')
        key = credential(config, args.env_file)
    output = prepare(config, selected, args.output, resume=getattr(args, 'resume', False))
    if args.command == 'prepare':
        print(json.dumps({'output': str(output), 'prepared_requests': len(selected), 'network_calls': 0})); return 0
    if args.command == 'run':
        with run_lock(output):
            return run(config, selected, output, key)
    if args.command == 'score':
        records = import_records(args.responses, selected)
        score_records(config, selected, records, output, 'imported_outputs')
    else:
        if config['prompt_variant'] != args.provider:
            raise ValueError('Replay provider and prompt_variant must match')
        score_records(config, selected, archived_outputs(selected, args.provider), output, 'archived_outputs')
        if args.checks:
            subprocess.run([sys.executable, '-B', str(ROOT / 'studies/replay_saved.py'), '--group', 'all',
                            '--output', str(output / 'saved_studies')], cwd=ROOT, check=True)
    return 0
