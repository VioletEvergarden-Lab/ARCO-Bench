"""Offline tests: real local HTTP transport, frozen fixtures, no paid APIs."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.config import load as load_config
from benchmark.data import PRIMARY, SUITES, archived_outputs, canonical, cases, public_task, read
from benchmark.runner import prepare
from benchmark.storage import run_lock, write


class Service:
    def __init__(self, mode='chat', fault=None):
        self.mode = mode; self.fault = fault; self.posts = []; self.gets = []; self.pending = {}
        self.key = 'local-test-credential'
        selected = cases(PRIMARY, 'luna')
        self.answers = {c['public_record_id']: r['raw_text'] for c, r in zip(selected, archived_outputs(selected, 'luna'))}

    def start(self):
        service = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def send(self, status, value):
                data = json.dumps(value).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.headers.get('Authorization') != 'Bearer ' + service.key:
                    self.send(401, {'error': 'test authentication failed'}); return
                messages = body.get('messages', body.get('input'))
                task = json.loads(messages[-1]['content'].rsplit('Public task:', 1)[1])
                if any(k in task for k in ('reference_plan', 'reference', 'optimal_plan', 'target_witness')):
                    self.send(400, {'error': 'reference leaked to generator'}); return
                service.posts.append(body)
                if service.fault == 'http_error':
                    self.send(429, {'error': service.key}); return
                if service.fault == 'credential_echo':
                    self.send(200, {'echo': service.key}); return
                text = service.answers[task['record_id']]
                if service.fault == 'invalid_answer': text = '{not valid JSON'
                if service.fault == 'nonfinite': text = '{"record_id":"' + task['record_id'] + '","decisions":NaN}'
                if service.fault == 'invalid_field_type':
                    answer = json.loads(text)
                    next(d for d in answer['decisions'] if not d['held'])['path_id'] = []
                    text = json.dumps(answer)
                model = 'different-model' if service.fault == 'model_mismatch' else body['model']
                if service.mode in ('responses', 'responses_sync'):
                    rid = 'resp_test_' + str(len(service.posts))
                    service.pending[rid] = dict(id=rid, model=model, status='completed', usage={'output_tokens': 1},
                                               output=[{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}])
                    self.send(200, service.pending[rid] if service.mode == 'responses_sync' else
                              dict(id=rid, model=model, status='queued', output=[]))
                elif service.mode == 'custom':
                    self.send(200, dict(model=model, answer=text, done=True))
                elif service.fault == 'invalid_envelope':
                    self.send(200, dict(model=model, choices=['unexpected']))
                else:
                    self.send(200, dict(model=model, choices=[{'finish_reason': 'length' if service.fault == 'length' else 'stop',
                                                             'message': {'role': 'assistant', 'content': text}}], usage={'completion_tokens': 1}))

            def do_GET(self):
                service.gets.append(self.path)
                rid = self.path.rsplit('/', 1)[-1]
                if service.fault == 'poll_once':
                    service.fault = None; self.send(503, {'error': 'temporary test outage'}); return
                self.send(200, service.pending[rid])

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        return 'http://127.0.0.1:' + str(self.server.server_port) + '/v1'

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='arco-interface-test-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'run_benchmark.py'), *map(str, args)],
                                cwd=self.root, capture_output=True, text=True, encoding='utf-8', timeout=180)
        self.assertEqual(result.returncode, expected, result.stdout[-2500:] + result.stderr[-2500:])
        self.assertNotIn('local-test-credential', result.stdout + result.stderr)
        return result

    @contextmanager
    def service(self, mode='chat', fault=None, suites=None):
        service = Service(mode, fault); base_url = service.start()
        config = dict(name='local transport test', model='test-model', base_url=base_url, api_key_env='BENCH_TEST_TOKEN',
                      adapter={'chat': 'chat_completions', 'responses': 'responses', 'responses_sync': 'responses',
                               'custom': 'benchmark.example_adapter:Adapter'}[mode],
                      prompt_variant='luna', suites=suites or list(PRIMARY), concurrency=2, parameters={},
                      poll_seconds=.01, poll_window_seconds=2, timeout_seconds=5, poll_timeout_seconds=5)
        cfg = self.root / ('config_' + mode + '.json'); write(cfg, config)
        env = self.root / 'keys.env'; env.write_text('BENCH_TEST_TOKEN="' + service.key + '"\n')
        try:
            yield service, cfg, env
        finally:
            service.close()

    def test_paper_requests_are_exact_for_all_suites(self):
        for provider in ('deepseek', 'luna'):
            config = load_config(ROOT / 'configs' / ('paper_' + provider + '.json'))
            selected = cases(SUITES, provider)
            output = prepare(config, selected, self.root / provider)
            self.assertEqual(len(selected), 183)
            for case in selected:
                body = read(output / 'requests' / (case['attempt_id'] + '.json'))['body']
                self.assertEqual(body, case['body'])
                self.assertEqual(public_task(case)['record_id'], case['public_record_id'])

    def test_saved_results_match_all_paper_primary_counts(self):
        expected = {'deepseek': [69, 24, 19, 13], 'luna': [68, 32, 22, 15]}
        for provider in expected:
            output = self.root / provider
            self.cli('replay', '--provider', provider, '--output', output)
            groups = read(output / 'summary.json')['groups']
            self.assertEqual([groups[s]['reference_quality'] for s in PRIMARY], expected[provider])
            self.assertEqual(groups['core72']['selected_reference_quality'], 71)
            self.assertEqual(groups['adds15']['reference_quality_within_600s'], 9 if provider == 'deepseek' else 11)

    def test_chat_http_all_147_tasks_then_import_and_rescore(self):
        with self.service() as (service, cfg, env):
            output = self.root / 'chat'
            self.cli('run', '--config', cfg, '--env-file', env, '--output', output)
            self.assertEqual(len(service.posts), 147)
            groups = read(output / 'summary.json')['groups']
            self.assertEqual([groups[s]['reference_quality'] for s in PRIMARY], [68, 32, 22, 15])
            imported = self.root / 'imported'
            self.cli('score', '--config', cfg, '--responses', output / 'responses.jsonl', '--output', imported)
            self.assertEqual(groups, read(imported / 'summary.json')['groups'])
            self.cli('run', '--config', cfg, '--env-file', env, '--output', output, '--resume')
            self.assertEqual(len(service.posts), 147)
            for path in output.rglob('*'):
                if path.is_file(): self.assertNotIn(service.key.encode(), path.read_bytes())

    def test_responses_async_and_custom_adapter_cover_four_verifiers(self):
        ids = [cases([s], 'luna')[0]['record_id'] for s in PRIMARY]
        for mode in ('responses', 'responses_sync', 'custom'):
            with self.service(mode) as (service, cfg, env):
                output = self.root / mode
                filters = [v for rid in ids for v in ('--record-id', rid)]
                self.cli('run', '--config', cfg, '--env-file', env, '--output', output, *filters)
                self.assertEqual(len(service.posts), 4)
                self.assertEqual(len(service.gets), 4 if mode == 'responses' else 0)
                self.assertEqual(set(read(output / 'summary.json')['groups']), set(PRIMARY))

    def test_accepted_response_resume_uses_get_only(self):
        with self.service('responses', 'poll_once', ['core72']) as (service, cfg, env):
            output = self.root / 'resume'
            args = ('run', '--config', cfg, '--env-file', env, '--output', output, '--limit', '1')
            self.cli(*args, expected=2)
            self.assertEqual(len(service.posts), 1)
            summary = read(output / 'summary.json')['groups']['core72']
            self.assertEqual(summary['evaluated_outputs'], 0)
            self.cli(*args, '--resume')
            self.assertEqual(len(service.posts), 1)
            self.assertEqual(len(service.gets), 2)
            self.assertEqual(read(output / 'summary.json')['groups']['core72']['reference_quality'], 1)

    def test_failed_requests_are_not_model_answers_and_secrets_are_absent(self):
        for fault in ('http_error', 'credential_echo', 'model_mismatch', 'invalid_envelope'):
            with self.service('chat', fault, ['core72']) as (service, cfg, env):
                output = self.root / fault
                self.cli('run', '--config', cfg, '--env-file', env, '--output', output, '--limit', '1', expected=2)
                summary = read(output / 'summary.json')['groups']['core72']
                self.assertEqual(summary['evaluated_outputs'], 0)
                self.assertIsNone(summary['reference_quality_rate'])
                self.assertEqual((output / 'responses.jsonl').read_text(), '')
                self.assertEqual(len(service.posts), 1)
                for p in output.rglob('*'):
                    if p.is_file(): self.assertNotIn(service.key.encode(), p.read_bytes())

    def test_invalid_or_truncated_model_outputs_are_scored_as_unsuccessful(self):
        for fault in ('invalid_answer', 'nonfinite', 'invalid_field_type', 'length'):
            with self.service('chat', fault, ['core72']) as (service, cfg, env):
                output = self.root / fault
                self.cli('run', '--config', cfg, '--env-file', env, '--output', output, '--limit', '1')
                summary = read(output / 'summary.json')['groups']['core72']
                self.assertEqual(summary['evaluated_outputs'], 1)
                self.assertEqual(summary['reference_quality'], 0)
                self.assertEqual(summary['reference_quality_rate'], 0)

    def test_ambiguous_submission_does_not_repeat_post(self):
        with self.service(suites=['core72']) as (service, cfg, env):
            output = self.root / 'ambiguous'
            config = load_config(cfg); selected = cases(['core72'], 'luna')[:1]
            prepare(config, selected, output)
            from benchmark.data import digest
            from benchmark.transport import utc
            c = selected[0]; req = read(output / 'requests' / (c['attempt_id'] + '.json'))
            write(output / 'attempts' / c['attempt_id'] / 'submission.json',
                  {'started_utc': utc(), 'request_sha256': digest(canonical(req)), 'post_intents': 1})
            self.cli('run', '--config', cfg, '--env-file', env, '--output', output, '--limit', '1', '--resume', expected=2)
            self.assertEqual(service.posts, [])

    def test_modified_requests_and_duplicate_imports_are_rejected(self):
        cfg = ROOT / 'configs/paper_deepseek.json'; output = self.root / 'inputs'
        self.cli('prepare', '--config', cfg, '--output', output, '--limit', '1')
        p = next((output / 'requests').glob('*.json')); data = read(p); data['body']['model'] = 'changed'; write(p, data)
        self.cli('prepare', '--config', cfg, '--output', output, '--limit', '1', expected=2)
        response = self.root / 'responses.jsonl'; response.write_text(2 * (json.dumps({'record_id': 'CA12_CORE_001', 'raw_text': '{}'}) + '\n'))
        self.cli('score', '--config', cfg, '--responses', response, '--output', self.root / 'duplicates', '--limit', '1', expected=2)

    def test_a_run_directory_cannot_be_used_by_two_processes(self):
        with self.service(suites=['core72']) as (service, cfg, env):
            output = self.root / 'locked'
            self.cli('prepare', '--config', cfg, '--output', output, '--limit', '1')
            with run_lock(output):
                result = self.cli('run', '--config', cfg, '--env-file', env, '--output', output, '--limit', '1', expected=2)
                self.assertIn('Another process', result.stdout)
            self.assertEqual(service.posts, [])

    def test_public_validation_does_not_read_reference_files(self):
        script = '''import sys
from pathlib import Path
from benchmark.data import ROOT, PRIMARY, cases, archived_outputs
fixtures = {}
for suite in PRIMARY:
 c = cases([suite], 'luna')[0]; fixtures[suite] = (c, archived_outputs([c], 'luna')[0]['raw_text'])
def audit(event,args):
 if event == 'open' and args and isinstance(args[0], (str,bytes)):
  p=str(args[0]).replace(chr(92),'/')
  if '/private/' in p or '/references/' in p or '/runs/deterministic/' in p or p.endswith('public_domain.jsonl'):
   raise RuntimeError('Reference read before public validation')
sys.addaudithook(audit)
from benchmark.evaluate import Evaluator
suite=sys.argv[1]; c,text=fixtures[suite]; e=Evaluator(suite,'luna'); assert e.validate(c['attempt_id'],text)['admissible']
'''
        for suite in PRIMARY:
            result = subprocess.run([sys.executable, '-B', '-c', script, suite], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
