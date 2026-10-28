"""Freeze source-selected tasks after the pre-generation validity checks."""
from pathlib import Path
import hashlib,json
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=['analysis/instance_source_check.json','analysis/runtime_validation.json','analysis/grid_design_probe.json','analysis/candidate_driver_checks.json']
for p in checks:
 value=read(ROOT/p)
 assert value.get('status')=='PASS',(p,value.get('status'))
dest=ROOT/'instances/FROZEN.json'
if dest.exists():raise RuntimeError('Already frozen; no overwrite')
design=read(ROOT/'instances/DESIGN.json')
for row in design['tasks']:assert sha(ROOT/row['task_path'])==row['sha256']
assert len(design['tasks'])==15
files=[ROOT/p for p in checks]
files+=list((ROOT/'runtime').glob('*.py'))+list((ROOT/'runtime').glob('*.json'))
files+=[ROOT/p for p in ['analysis/input_selection.json','analysis/pre_freeze_design_decision.md','source/ADDS_public_instructions.md','analysis/pipeline_protocol.json']]
frozen={**design,'frozen':True,'frozen_utc':datetime.now(timezone.utc).isoformat(),'planned_first_requests':30,
 'selection_before_formal_outcomes':True,'development_excluded':True,
 'inputs':[{ 'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in files]}
dest.write_text(json.dumps(frozen,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'frozen':True,'tasks':len(frozen['tasks']),'planned_first_requests':30,'sha256':sha(dest)}))
