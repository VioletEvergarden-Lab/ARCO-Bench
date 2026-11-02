"""Run the existing verifiers in isolated, network-disabled worker processes."""
import contextlib
import importlib
import json
import math
import socket
import subprocess
import sys
import threading
from pathlib import Path
from benchmark.data import ROOT, OLD, PAIRED, ADDS, cases, public_task, read


def deny(*args, **kwargs):
    raise RuntimeError('Networking and optimization are disabled in evaluation')


class Evaluator:
    def __init__(self, suite, provider):
        socket.create_connection = socket.socket.connect = socket.getaddrinfo = deny
        self.suite = suite
        self.cases = {c['attempt_id']: c for c in cases([suite], provider)}
        self.tasks = {k: public_task(c) for k, c in self.cases.items()}
        self.references = None
        self.reference_checks = {}
        if suite in ('core72', 'core_anchors'):
            import admit
            self.public = admit.public_runtime()
            self.private = None
        elif suite == 'adds15':
            sys.path.insert(0, str(ADDS / 'scripts'))
            from adds_runtime import load_runtime
            self.engine, *_ = load_runtime()
        else:
            sys.path.insert(0, str(OLD))
            self.engine = importlib.import_module('continuous_engine')
        import scipy.optimize
        import highspy
        scipy.optimize.milp = highspy.Highs.run = deny

    def validate(self, aid, text):
        c = self.cases[aid]; task = self.tasks[aid]
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError('Non-finite JSON number')
            if isinstance(value, dict):
                for v in value.values(): finite(v)
            elif isinstance(value, list):
                for v in value: finite(v)
        try:
            finite(json.loads(text))
        except (ValueError, TypeError, RecursionError):
            return dict(schema_valid=False, admissible=False, objective=None, errors=['SCHEMA_JSON'])
        if self.suite in ('core72', 'core_anchors'):
            selector, formal = self.public
            try:
                parsed, errors = selector.parse_public(text, task)
                v = selector.public_evaluate(parsed, errors, task, formal)
            except (TypeError, KeyError, AttributeError, ValueError, IndexError, OverflowError):
                return dict(schema_valid=False, admissible=False, objective=None, errors=['SCHEMA_DECISION_TYPE'])
            return dict(schema_valid=bool(v['schema_valid']), admissible=bool(v['schema_valid'] and v['formal_feasible']),
                        objective=v.get('objective_vector'), verification=v,
                        errors=v.get('parse_errors', []) + v.get('formal_error_codes', []))
        decisions, errors = self.engine.parse(text, task)
        if errors:
            return dict(schema_valid=False, admissible=False, objective=None, errors=errors)
        try:
            v = self.engine.Engine(task).verify(decisions)
        except (TypeError, KeyError, AttributeError, ValueError, IndexError, OverflowError):
            return dict(schema_valid=False, admissible=False, objective=None, errors=['SCHEMA_DECISION_TYPE'])
        return dict(schema_valid=not any(e.startswith('SCHEMA_') for e in v['errors']),
                    admissible=bool(v['admissible']), objective=v['objective'], errors=v['errors'], verification=v)

    def quality(self, aid, text, v):
        c = self.cases[aid]; rid = c['record_id']
        if self.suite in ('core72', 'core_anchors'):
            import rescore
            if self.private is None:
                self.private = rescore.runtime()
                self.references = {r['record_id']: r for r in rescore.rows(ROOT / 'references/public_domain.jsonl')}
            result = rescore.score([dict(record_id=rid, raw_text=text if v['schema_valid'] else '')], self.private)[0]
            if result['online_admissible'] != v['admissible']:
                raise RuntimeError('Public/private verifier disagreement')
            return dict(reference_quality=result['reference_quality'], reference_certified=True,
                        reference_objective=self.references[rid]['objective'],
                        first_difference=result['lexicographic_first_difference'],
                        construct_fidelity=result['construct_fidelity'])
        if self.suite == 'adds15':
            p = ADDS / 'runs/deterministic' / (rid + '__Full-MILP.json')
        elif self.suite in ('paired24', 'paired_repeats'):
            p = PAIRED / 'new_networks/references' / (rid + '.json')
        else:
            p = OLD / 'networks/references' / (rid + '.json')
        ref = read(p)
        certified = bool(ref.get('optimal') or ref.get('global_optimal'))
        if aid not in self.reference_checks:
            verified = self.engine.Engine(self.tasks[aid]).verify(ref['decisions'])
            if not verified['admissible'] or not self.engine.quality(verified['objective'], ref['objective']):
                raise RuntimeError('Stored reference failed independent validation')
            self.reference_checks[aid] = True
        rq = bool(v['admissible'] and self.engine.quality(v['objective'], ref['objective'])) if certified else None
        if v['admissible'] and certified and self.engine.compare(v['objective'], ref['objective']) < 0:
            raise RuntimeError('Candidate improves a claimed certified optimum; inspect the reference')
        first = next((f'L{i+1}' for i, (k, tol) in enumerate(zip(self.engine.TIERS, self.engine.QUALITY_TOL))
                      if abs(v['objective'][k] - ref['objective'][k]) > tol + 1e-10), None) if v['admissible'] else None
        return dict(reference_quality=rq, reference_certified=certified, reference_objective=ref['objective'], first_difference=first)

    def greedy(self, aid):
        c = self.cases[aid]; rid = c['record_id']
        if self.suite in ('core72', 'core_anchors'):
            if not hasattr(self, 'policy'):
                self.policy = {r['record_id']: r['raw_text'] for r in
                               (json.loads(s) for s in (ROOT / 'responses/policy.jsonl').read_text().splitlines() if s)}
            return self.policy[rid]
        if self.suite == 'adds15':
            p = ADDS / 'runs/deterministic' / (rid + '__G.json')
        else:
            folder = 'new_comparison' if self.suite in ('paired24', 'paired_repeats') else 'comparison'
            p = PAIRED / 'results' / folder / 'runs' / (rid + '__G.json')
        return json.dumps(dict(record_id=c['public_record_id'], decisions=read(p)['decisions']))

    def score(self, aid, text, eligible=True):
        v = self.validate(aid, text) if eligible else dict(schema_valid=False, admissible=False, objective=None, errors=[])
        result = {**v, **self.quality(aid, text if eligible else '', v)}
        # Selection is decided from public feasibility/objectives only, before
        # evaluating the quality of the chosen plan. A tie keeps the greedy plan.
        greedy_text = self.greedy(aid); g = self.validate(aid, greedy_text)
        compare = self.public[0].lex_compare if self.suite in ('core72', 'core_anchors') else self.engine.compare
        pick_g = g['admissible'] and (not v['admissible'] or compare(g['objective'], v['objective']) <= 0)
        selected = g if pick_g else v
        chosen_text = greedy_text if pick_g else text if eligible else ''
        q = self.quality(aid, chosen_text, selected)
        result['selection'] = dict(source='greedy' if pick_g else 'model' if v['admissible'] else None,
                                   admissible=selected['admissible'], objective=selected['objective'],
                                   reference_quality=q['reference_quality'],
                                   decisions=json.loads(chosen_text)['decisions'] if selected['admissible'] else None)
        return result


class Worker:
    def __init__(self, suite, provider):
        self.lock = threading.Lock()
        self.process = subprocess.Popen([sys.executable, '-B', '-m', 'benchmark.evaluate', suite, provider],
                                        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding='utf-8', bufsize=1)
        hello = self.process.stdout.readline()
        if not hello or json.loads(hello).get('ready') is not True:
            self.close()
            raise RuntimeError('Evaluator startup failed; install requirements-studies.txt')

    def call(self, operation, case, text='', eligible=True):
        with self.lock:
            self.process.stdin.write(json.dumps(dict(operation=operation, aid=case['attempt_id'], text=text, eligible=eligible)) + '\n')
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError('Evaluator stopped unexpectedly')
            result = json.loads(line)
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result['result']

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate(); self.process.wait(timeout=5)
        self.process.stdout.close(); self.process.stderr.close()


def main():
    with contextlib.redirect_stdout(sys.stderr):
        evaluator = Evaluator(*sys.argv[1:])
    print(json.dumps({'ready': True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if request['operation'] == 'validate':
                    result = evaluator.validate(request['aid'], request['text'])
                elif request['operation'] == 'score':
                    result = evaluator.score(request['aid'], request['text'], request['eligible'])
                else:
                    raise ValueError('Unknown evaluator operation')
            reply = {'result': result}
        except Exception as exc:
            reply = {'error': type(exc).__name__ + ': evaluator rejected the record or stored reference'}
        print(json.dumps(reply, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
