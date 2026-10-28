"""One-shot queue: finish the already-running new batch, then run the old batch.

This is a local computation queue, with no scheduling service or model calls.
"""
from pathlib import Path
import json, subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/comparison'
OUT.mkdir(parents=True,exist_ok=True)
while True:
    done=list((ROOT/'results/new_comparison/runs').glob('*__*.json'))
    if len(done)==120: break
    if (OUT/'PAUSE').exists(): raise SystemExit('Pause requested before original-network batch')
    time.sleep(10)
time.sleep(5)
with (OUT/'batch_console.txt').open('a',encoding='utf-8') as log:
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/run_comparison.py')],stdout=log,stderr=subprocess.STDOUT)
if proc.returncode: raise SystemExit(proc.returncode)
with (OUT/'summary_console.txt').open('w',encoding='utf-8') as log:
    subprocess.run([sys.executable,str(ROOT/'scripts/optimization_summary.py')],stdout=log,stderr=subprocess.STDOUT,check=True)
print('Both new and original deterministic batches finished.',flush=True)
