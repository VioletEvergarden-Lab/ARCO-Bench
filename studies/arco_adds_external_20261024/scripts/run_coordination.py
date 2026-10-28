"""Target-conditioned scalar and joint scope from the same formal G origin."""
from pathlib import Path
import json,sys
sys.dont_write_bytecode=True
from run_deterministic import ROOT,read,write,digest,ce,CoordinationProblem,changes,target_met

def checked(query,task,origin,ref,prefix):
 if query['decisions'] is not None:
  v=ce.Engine(task).verify(query['decisions']);assert v['admissible']
  assert target_met(v['objective'],ref['objective'],prefix)
  ms,us=changes(query['decisions'],origin)
  assert len(ms)==query['mission_changes'] and len(us)==query['chain_changes']
  if query['chain_budget'] is not None:assert len(us)<=query['chain_budget']
 return query

def main():
 manifest=read(ROOT/'instances/FROZEN.json');rows=[];frontiers=[]
 for item in manifest['tasks']:
  rid=item['record_id'];task=read(ROOT/item['task_path']);assert digest(ROOT/item['task_path'])==item['sha256']
  ref=read(ROOT/'runs/deterministic'/f'{rid}__Full-MILP.json');assert ref['global_optimal']
  origin=read(ROOT/'runs/deterministic'/f'{rid}__G.json')['decisions']
  cp=CoordinationProblem(task,origin,origin_name='formal_G')
  for prefix in [2,3,4,6]:
   group=[]
   for metric in ['missions','chains']:
    out=ROOT/'runs/coordination'/f'{rid}__T{prefix}__{metric}.json'
    q=read(out) if out.exists() else cp.solve(ref['objective'],target_prefix=prefix,minimize=metric,seconds=60.,witness=ref['decisions'])
    checked(q,task,origin,ref,prefix);write(out,q)
    rows.append(dict(record_id=rid,base_id=item['base_id'],condition=item['condition'],target='T'+str(prefix),metric=metric,lower=q['lower_bound'],upper=q['upper_bound'],status=q['status'],seconds=q['elapsed_seconds'],query_path=out.relative_to(ROOT).as_posix()))
   for k in range(4):
    out=ROOT/'runs/coordination'/f'{rid}__T{prefix}__joint_k{k}.json'
    if out.exists():q=read(out)
    elif k==3:
     q=dict(read(ROOT/'runs/coordination'/f'{rid}__T{prefix}__missions.json'));q['chain_budget']=3;q['reused_from']='unrestricted missions query; all 3 chains allowed'
    else:q=cp.solve(ref['objective'],target_prefix=prefix,minimize='missions',chain_budget=k,seconds=60.,witness=ref['decisions'])
    checked(q,task,origin,ref,prefix);write(out,q)
    group.append(dict(chain_cap=k,lower=q['lower_bound'],upper=q['upper_bound'],status=q['status'],mission_changes=q['mission_changes'],chain_changes=q['chain_changes'],query_path=out.relative_to(ROOT).as_posix()))
   feasible=[(q['mission_changes'],q['chain_changes']) for q in group if q['upper'] is not None]
   pareto=sorted(set(p for p in feasible if not any(z!=p and z[0]<=p[0] and z[1]<=p[1] for z in feasible)))
   frontiers.append(dict(record_id=rid,target='T'+str(prefix),chain_cap_queries=group,verified_pareto_pairs=pareto,all_cap_queries_resolved=all(q['status'] in ('optimal','infeasible') for q in group)))
  print(json.dumps(dict(record_id=rid,completed=True)),flush=True)
 write(ROOT/'analysis/scope_panel.json',dict(origin='formal_G',targets=[2,3,4,6],rows=rows,joint_frontiers=frontiers))
 print(json.dumps(dict(scalar_rows=len(rows),exact=sum(r['lower']==r['upper'] and r['upper'] is not None for r in rows),frontiers=len(frontiers),resolved=sum(f['all_cap_queries_resolved'] for f in frontiers))),flush=True)
if __name__=='__main__':main()
