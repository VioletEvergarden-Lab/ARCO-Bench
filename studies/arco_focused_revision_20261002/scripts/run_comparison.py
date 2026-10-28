"""Sequential, resumable timed batch. Never shares G across distinct methods."""
from pathlib import Path
import argparse
import hashlib
import json
import platform
import time
_import_start = time.perf_counter()
from optimization_online import run_online, METHODS, PROTOCOL, ROOT, VERSION, HIST
_runtime_import_seconds = time.perf_counter() - _import_start


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tasks', type=Path, default=ROOT/'arco_closing_study/networks/tasks')
    p.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1]/'results/comparison/runs')
    p.add_argument('--ids', nargs='*')
    p.add_argument('--methods', nargs='+', default=list(METHODS), choices=METHODS)
    p.add_argument('--budget', type=float, default=600.)
    p.add_argument('--slice-seconds', type=float, default=60.)
    p.add_argument('--pause-file', type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pause_file = args.pause_file or args.output.parent/'PAUSE'
    runtime = {'protocol':PROTOCOL, 'python':platform.python_version(),
               'platform':platform.platform(), 'processor':platform.processor(),
               'highs':VERSION, 'one_time_runtime_import_seconds':_runtime_import_seconds,
               'engine_sha256':hashlib.sha256((HIST/'continuous_engine.py').read_bytes()).hexdigest(),
               'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'solver_sha256':hashlib.sha256((Path(__file__).parent/'optimization_online.py').read_bytes()).hexdigest()}
    runtime_path = args.output.parent/('runtime_'+str(time.time_ns())+'.json')
    runtime_path.write_text(json.dumps(runtime,indent=2),encoding='utf-8')
    task_paths = sorted(args.tasks.glob('*.json'))
    if args.ids:
        selected = set(args.ids)
        task_paths = [q for q in task_paths if q.stem in selected]
        if {q.stem for q in task_paths} != selected:
            raise ValueError('missing requested tasks')
    # L02-B is a declared diagnostic priority, followed by fixed task-ID order.
    task_paths.sort(key=lambda q: (q.stem != 'NET_L02_B', q.stem))
    started = time.perf_counter()
    for task_path in task_paths:
        for method in args.methods:
            if pause_file.exists():
                print('PAUSED between completed task-method runs:',pause_file,flush=True)
                return
            out = args.output/f'{task_path.stem}__{method}.json'
            if out.exists():
                old = json.loads(out.read_text(encoding='utf-8'))
                if (old['protocol'] != PROTOCOL or old['budget_seconds'] != args.budget or
                    old['slice_seconds'] != args.slice_seconds or
                    old['task_sha256'] != hashlib.sha256(task_path.read_bytes()).hexdigest()):
                    raise RuntimeError('existing result uses another protocol: '+str(out))
                print('RESUME', task_path.stem, method, flush=True)
                continue
            # Exact same S configuration: retain explicit provenance, not a run.
            if method == 'R_frac':
                task = json.loads(task_path.read_text(encoding='utf-8'))
                if len(task['missions']) <= 16:
                    source = args.output/f'{task_path.stem}__R4.json'
                    if source.exists():
                        result = json.loads(source.read_text(encoding='utf-8'))
                        result.update(method='R_frac', reused_from=source.name,
                                      reuse_reason='same public input, k=4 and total budget')
                    else:
                        result = run_online(task_path, 'R4', args.budget, args.slice_seconds)
                        source.write_text(json.dumps(result, indent=2), encoding='utf-8')
                        result.update(method='R_frac', reused_from=source.name,
                                      reuse_reason='same public input, k=4 and total budget')
                else:
                    result = run_online(task_path, method, args.budget, args.slice_seconds)
            else:
                result = run_online(task_path, method, args.budget, args.slice_seconds)
            tmp = out.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(result, indent=2), encoding='utf-8')
            tmp.replace(out)
            print('DONE', task_path.stem, method, round(result['total_seconds'], 3),
                  result['objective'], 'batch_seconds', round(time.perf_counter()-started, 1), flush=True)


if __name__ == '__main__':
    main()
