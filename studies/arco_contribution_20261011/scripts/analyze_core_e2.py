"""Controlled Core E2: four complete Luna misses and four DeepSeek controls.
Only replay saved decisions and derive support/budget answers; no optimization/API.
Run: D:\\Code\\python.exe arco_contribution_20261011/scripts/analyze_core_e2.py
"""
from pathlib import Path
from collections import Counter
import csv,json,sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parents[1];W=HERE.parent
P=W.parent
R=W/'arco_codex_research_20260925';C=W/'arco_closing_study'
sys.path.insert(0,str(C))
from study_common import Runtime,TIERS
from coordination_solver import canonical_plan,changes,target_met
TOL=(0.,0.,0.,0.,0.,1e-4)
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def jl(p):return [json.loads(x) for x in p.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def rel(p):return __import__('os').path.relpath(p,W).replace('\\','/')
def write(name,rows):
 p=HERE/'analysis'/name
 if name.endswith('.json'):p.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');return
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  wr=csv.DictWriter(f,fieldnames=keys);wr.writeheader()
  wr.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()} for r in rows)
def main():
 ids=[f'CA12_CORE_{n:03d}' for n in [16,34,46,63]]
 refs={r['record_id']:r for r in jl(P/'references/public_domain.jsonl')}
 gs={r['record_id']:json.loads(r['raw_text'])['decisions'] for r in jl(R/'policy_domains/public_both.jsonl')}
 models={s:{r['record_id']:r for r in jl(P/'responses'/f'{s}_complete.jsonl')} for s in ['luna','deepseek']}
 master={(r['record_id'],r['source']):r for r in jl(P/'results/current/MASTER.jsonl')}
 distance_path=HERE/'runs/development/CA12_CORE_034__T6__missions.json'
 distance=read(distance_path)
 assert distance['optimal'] and distance['lower_bound']==distance['upper_bound']==4
 assert distance['status']=='optimal' and distance['origin_name']=='G' and distance['target_prefix']==6
 archived_dist=next(r for r in read(W/'arco_codex_research_20260930/coordination/results.json') if r['task']=='CA12_CORE_034')
 assert archived_dist['k_star']==archived_dist['distance_lower_bound']==4 and archived_dist['mip_gap']==0
 rt=Runtime();candidates=[];queries=[];plans=[]
 for rid in ids:
  task_path=P/'data/public/records'/f'{rid}.json';task=read(task_path)
  g=canonical_plan(gs[rid],task);target=refs[rid]['objective']
  pool=[('G',g,R/'policy_domains/public_both.jsonl'),('reference',canonical_plan(refs[rid]['decisions'],task),P/'references/public_domain.jsonl')]
  for model in models:
   ds=canonical_plan(json.loads(models[model][rid]['raw_text'])['decisions'],task)
   pool.append((model,ds,P/'responses'/f'{model}_complete.jsonl'))
  verified={}
  for name,ds,path in pool:
   ev=rt.evaluate(task,ds);ms,us=changes(ds,g)
   verified[name]=dict(decisions=ds,admissible=bool(ev['formal_feasible']),objective=ev.get('objective_vector'),errors=ev.get('formal_errors',[]),changed_missions=ms,changed_uavs=us,source=rel(path))
   plans.append(dict(record_id=rid,name=name,**verified[name]))
  assert verified['G']['admissible'] and verified['reference']['admissible']
  assert target_met(verified['reference']['objective'],target,6,tolerances=TOL)
  if rid=='CA12_CORE_034':
   assert canonical_plan(distance['decisions'],task)==verified['reference']['decisions']
  for model in models:
   v=verified[model];m=master[rid,model+'_complete'];k=len(v['changed_missions']);S=v['changed_uavs']
   assert bool(m['schema']) and v['admissible']==bool(m['formal'])
   quality=v['admissible'] and target_met(v['objective'],target,6,tolerances=TOL)
   assert quality==bool(m['reference_quality'])
   losses=[i for i,t in enumerate(TIERS) if v['admissible'] and abs(v['objective'][t]-target[t])>TOL[i]]
   candidates.append(dict(record_id=rid,model=model,origin='G',candidate_admissible=v['admissible'],candidate_quality=quality,candidate_errors=v['errors'],first_loss=('L'+str(losses[0]+1)) if losses else None,candidate_k=k,candidate_support=S,candidate_changed_missions=v['changed_missions'],candidate_objective=v['objective'],reference_objective=target,candidate_source=v['source']))
   for j in [2,3,6]:
    for budget in [None,k]:
     feasible=[(name,p) for name,p in verified.items() if p['admissible'] and target_met(p['objective'],target,j,tolerances=TOL) and set(p['changed_uavs'])<=set(S) and (budget is None or len(p['changed_missions'])<=budget)]
     row=dict(record_id=rid,model=model,origin='G',target_prefix=j,target_mode='match',allowed_support=S,task_budget=budget,candidate_k=k,candidate_admissible=v['admissible'],candidate_target_met=v['admissible'] and target_met(v['objective'],target,j,tolerances=TOL),new_solver_calls=0)
     if feasible:
      name,p=min(feasible,key=lambda z:(len(z[1]['changed_missions']),len(z[1]['changed_uavs']),z[0]))
      cm,cu=changes(p['decisions'],v['decisions'])
      row.update(answer='feasible',proof_type='verified_stored_witness',witness_name=name,witness_k=len(p['changed_missions']),witness_support=p['changed_uavs'],witness_changed_missions=p['changed_missions'],witness_source=p['source'],witness_revisions_from_candidate=cm,witness_revision_count_from_candidate=len(cm),exclusion_source=None)
     else:
      assert rid=='CA12_CORE_034' and model=='luna' and j==6 and budget==3
      row.update(answer='infeasible',proof_type='inherited_global_distance_lower_bound',witness_name=None,witness_k=None,witness_support=None,witness_changed_missions=None,witness_source=None,witness_revisions_from_candidate=None,witness_revision_count_from_candidate=None,exclusion_source=rel(distance_path),global_k_lower_bound=4,archived_corroborating_source='arco_codex_research_20260930/coordination/results.json')
     queries.append(row)
 assert len(candidates)==8 and len(queries)==48
 assert Counter(q['answer'] for q in queries)=={'feasible':47,'infeasible':1}
 write('core_e2_candidates.json',candidates);write('core_e2_candidates.csv',candidates)
 write('core_e2_queries.json',queries);write('core_e2_queries.csv',queries);write('core_e2_plans.json',plans)
 summary=dict(completed='2026-10-12',controlled_task_ids=ids,selection='All four complete-decision Luna quality misses in stored Core-72, with corresponding DeepSeek quality controls; not a new task population',candidates=len(candidates),queries=len(queries),answers=dict(Counter(q['answer'] for q in queries)),new_solver_calls=0,new_model_calls=0,verification_replays=len(plans),claim='034 chosen UAV support is sufficient for quality, but its three-mission budget relative to G is insufficient; T3 loss is avoidable even with zero changes. Other three tasks have G as a quality witness within all tested supports and budgets.',distance_definition='Canonical held/path/departure/charge tuple differs from G; allowed support is a subset constraint, not an exact-support requirement',script=rel(Path(__file__)))
 write('core_e2_summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
