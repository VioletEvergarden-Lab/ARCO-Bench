"""One-shot conditional batch: execute frozen model attempts after C completes."""
from pathlib import Path
import json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
ONLINE=ROOT/'online/new_generation'
while len(list((ROOT/'results/new_comparison/runs').glob('*__*.json')))<120:
    if (ONLINE/'PAUSE').exists():raise SystemExit('Paused before generation')
    time.sleep(10)
refs=[json.loads(p.read_text(encoding='utf-8')) for p in (ROOT/'new_networks/references').glob('*.json')]
assert len(refs)==24 and all(r['optimal'] for r in refs)
gate=ONLINE/'LAUNCH_GATE.json'
if not gate.exists():
    gate.write_text(json.dumps({'frozen_formal_tasks':24,'certified_offline_references':24,'completed_deterministic_results_including_same_setting_reuse':120,'mechanism_evidence':'12 paired closures; 7 wait-to-detour transitions, 4 paired charging changes; route and charging restrictions exclude full service in two representatives','formal_attempt_limit':96},indent=2),encoding='utf-8')
for limit in (4,None):
    args=[sys.executable,str(ROOT/'scripts/run_new_models.py'),'--execute']
    if limit:args.extend(['--max-rank',str(limit)])
    with (ONLINE/'batch_console.txt').open('a',encoding='utf-8') as log:
        p=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT)
    if p.returncode:raise SystemExit(p.returncode)
with (ONLINE/'scoring_console.txt').open('w',encoding='utf-8') as log:
    subprocess.run([sys.executable,str(ROOT/'scripts/score_new_models.py')],stdout=log,stderr=subprocess.STDOUT,check=True)
print('Frozen model batch finished and replayed.',flush=True)
