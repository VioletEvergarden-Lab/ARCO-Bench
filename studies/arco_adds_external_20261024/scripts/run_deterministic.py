"""Resume the archived online methods on the frozen ADDS external group."""
from pathlib import Path
import argparse,copy,hashlib,json,sys
sys.dont_write_bytecode=True
from adds_runtime import load_runtime
ce,CoordinationProblem,changes,target_met,MODEL=load_runtime()
ROOT=Path(__file__).resolve().parents[1]
from optimization_online import run_online

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 temp=p.with_suffix('.tmp');temp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');temp.replace(p)
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def run_one(path,method,out,budget=600.):
 task=read(path)
 if out.exists():
  saved=read(out);assert saved['task_sha256']==digest(path)
  verified=ce.Engine(task).verify(saved['decisions']);assert verified['admissible']
  assert ce.compare(verified['objective'],saved['objective'])==0
  return saved
 result=run_online(path,method,budget=budget,slice_seconds=60.)
 assert result['admissible'],result
 verified=ce.Engine(task).verify(result['decisions']);assert verified['admissible'],verified
 assert ce.compare(verified['objective'],result['objective'])==0
 result['replay']=verified;write(out,result)
 print(json.dumps(dict(record_id=task['record_id'],method=method,seconds=round(result['total_seconds'],3),global_optimal=result['global_optimal'],objective=result['objective'])),flush=True)
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--development',action='store_true');p.add_argument('--methods',nargs='+',default=['G','R4','Full-MILP','Iter-R4','R_frac']);a=p.parse_args()
 if a.development:
  folder=ROOT/'runs/design_pilot'
  paths=[folder/'grid1_task.json',folder/'grid05_task.json']
  tasks=[read(f) for f in paths];engines=[ce.Engine(t) for t in tasks]
  signature=lambda e:{(m,o['path_id'],o['depart_min'],o['charge_blocks']) for m,opts in e.options().items() for o in opts}
  coarse=signature(engines[0]);fine=signature(engines[1]);assert coarse<=fine
  fixed_g=engines[0].greedy();scores=[e.verify(fixed_g) for e in engines];assert all(s['admissible'] for s in scores)
  assert ce.compare(scores[0]['objective'],scores[1]['objective'])==0
  refs=[run_one(f,'Full-MILP',folder/(f.stem+'_reference.json')) for f in paths]
  assert all(r['global_optimal'] for r in refs),'Pilot reference not proved'
  queries=[]
  for i,(task,ref) in enumerate(zip(tasks,refs)):
   cp=CoordinationProblem(task,fixed_g,origin_name='same_coarse_G')
   for prefix in [2,3,4,6]:
    for metric in ['missions','chains']:
     dest=folder/f'grid{i}_T{prefix}_{metric}.json'
     q=read(dest) if dest.exists() else cp.solve(ref['objective'],target_prefix=prefix,minimize=metric,seconds=60.,witness=ref['decisions'])
     write(dest,q);queries.append(dict(grid=task['timing']['departure_grid_min'],target='new_T'+str(prefix),metric=metric,lower=q['lower_bound'],upper=q['upper_bound'],status=q['status']))
   if i==1:
    for metric in ['missions','chains']:
     dest=folder/f'fine_old_lex_{metric}.json'
     q=read(dest) if dest.exists() else cp.solve_lex_threshold(refs[0]['objective'],minimize=metric,seconds=60.,witness=[refs[0]['decisions'],ref['decisions']])
     write(dest,q);queries.append(dict(grid=.5,target='old_coarse_lex_threshold',metric=metric,lower=q['lower_bound'],upper=q['upper_bound'],status=q['status']))
  report=dict(status='PASS',purpose='Pre-freeze controlled grid check; excluded from formal group',same_incumbent=True,same_origin=True,same_due_times=True,same_resource_windows=True,same_capacity=2,coarse_options=len(coarse),fine_options=len(fine),nested=True,origin=scores[0]['objective'],references=[dict(grid=t['timing']['departure_grid_min'],objective=r['objective']) for t,r in zip(tasks,refs)],queries=queries)
  write(ROOT/'analysis/grid_design_probe.json',report);print(json.dumps(report,indent=2),flush=True)
  return
 manifest=read(ROOT/'instances/FROZEN.json');assert manifest['frozen']
 for row in manifest['tasks']:
  path=ROOT/row['task_path'];assert digest(path)==row['sha256']
  for method in a.methods:
   out=ROOT/'runs/deterministic'/f"{row['record_id']}__{method}.json"
   if method=='R_frac' and row['missions']<=16:
    prior=ROOT/'runs/deterministic'/f"{row['record_id']}__R4.json"
    if not prior.exists():run_one(path,'R4',prior)
    if not out.exists():
     result=copy.deepcopy(read(prior));result.update(method='R_frac',reused_from=prior.relative_to(ROOT).as_posix(),reuse_reason='max(4,ceil(M/4))=4; identical search');write(out,result)
   else:run_one(path,method,out)
if __name__=='__main__':main()
