"""E2: support versus decision choices, with identical-query MIP/reuse comparison."""
from pathlib import Path
from collections import Counter
import argparse,csv,json,sys,time,hashlib
sys.dont_write_bytecode=True
from coordination_study import ROOT,load_cases,read,write,meets
from coordination_solver import CoordinationProblem,canonical_plan,changes,TIERS,QUALITY_TOL
from query_reuse import Query,FeasibilityCache
SOURCES=('R4','Iter-R4','R_frac','deepseek','luna')

def prefix_of(obj,target):
 p=0
 for i,k in enumerate(TIERS):
  if abs(obj[k]-target[k])>QUALITY_TOL[i]+1e-10:break
  p=i+1
 return p

def key(j,s,k):
 return f'j{j}__'+('-'.join(sorted(s)) or 'empty')+f'__k{k if k is not None else "all"}'

def context(case):
 rows=[];queries={}
 for source in SOURCES:
  c=case['candidates'][source];base=dict(record_id=case['record_id'],group=case['group'],source=source,
   source_path=c['source_path'],status=c['status'],admissible=c['admissible'],reference_quality=c['reference_quality'],
   support=c['changed_uavs_vs_G'],mission_changes=c['dM_vs_G'])
  if not c['decisions'] or c['dM_vs_G'] is None:
   rows.append({**base,'included':False,'reason':'no complete evaluable decisions'});continue
  if c['reference_quality']:
   rows.append({**base,'included':True,'reason':'successful control; candidate itself proves support and budget sufficiency','diagnosis':'successful_control'});continue
  try:canonical_plan(c['decisions'],case['task'])
  except (KeyError,TypeError,ValueError):
   rows.append({**base,'included':False,'reason':'invalid decision schema'});continue
  qkeys={}
  for j in (2,6):
   for bounded in (False,True):
    k=c['dM_vs_G'] if bounded else None;qkey=key(j,c['changed_uavs_vs_G'],k)
    queries[qkey]=dict(prefix=j,allowed=c['changed_uavs_vs_G'],mission_budget=k)
    qkeys[f'T{j}_'+('budget' if bounded else 'support')]=qkey
  rows.append({**base,'included':True,'reason':'evaluable quality miss','queries':qkeys,
   'single_reference_support':case['candidates']['reference']['changed_uavs_vs_G'],
   'single_reference_fits_support':set(case['candidates']['reference']['changed_uavs_vs_G'])<=set(c['changed_uavs_vs_G']),
   'single_reference_fits_budget':case['candidates']['reference']['dM_vs_G']<=c['dM_vs_G']})
 return rows,queries

def run(seconds=30,only=None):
 cases=load_cases()
 for case in cases:
  rid=case['record_id']
  if only and rid not in only:continue
  candidates,queries=context(case)
  folder=ROOT/'runs'/'e2'/rid;write(folder/'candidates.json',candidates);write(folder/'queries.json',queries)
  if not queries:continue
  for mode in ('direct_static','cross_query_reuse'):
   done=folder/f'{mode}_complete.json'
   if done.exists():continue
   started=time.perf_counter();problem=CoordinationProblem(case['task'],case['origins']['G'],'G');cache=FeasibilityCache();static=[];seed_validation=0.
   for source,c in case['candidates'].items():
    if not c['decisions']:continue
    tick=time.perf_counter()
    try:
     plan=canonical_plan(c['decisions'],case['task']);score=problem.engine.verify(plan)
    except (KeyError,TypeError,ValueError):continue
    seed_validation+=time.perf_counter()-tick
    if score['admissible']:
     p=prefix_of(score['objective'],case['reference']['objective']);ms,us=changes(plan,problem.origin)
     static.append((p,us,len(ms),plan,source));cache.add_witness(p,us,len(ms),plan,'stored:'+source)
   records=[]
   ordered=sorted(queries.items(),key=lambda item:(item[1]['prefix'],len(item[1]['allowed']),item[1]['allowed'], -1 if item[1]['mission_budget'] is None else item[1]['mission_budget']))
   for qkey,spec in ordered:
    out=folder/mode/(qkey+'.json');q=Query.make(**spec)
    if out.exists():r=read(out)
    else:
     tick=time.perf_counter();known=cache.infer(q) if mode=='cross_query_reuse' else None
     if known:
      r={**known,'status':'feasible' if known['feasible'] else 'infeasible','solver_seconds':0.,'elapsed_seconds':time.perf_counter()-tick,'query':spec,'query_key':qkey,'mode':mode,'direct_solver_called':False}
     else:
      # Both variants receive the same stored complete plans. A direct query
      # may finish by checking a supplied witness, before invoking MIP.
      seeds=[plan for p,us,k,plan,src in static if p>=q.prefix and set(us)<=q.allowed and k<=q.mission_budget]
      r=problem.solve(case['reference']['objective'],target_prefix=spec['prefix'],minimize='feasibility',allowed_uavs=spec['allowed'],task_budget=spec['mission_budget'],seconds=seconds,witness=seeds or None)
      r.update(query=spec,query_key=qkey,mode=mode,evidence='direct_restricted_MIP_or_static_witness',direct_solver_called=r['solver_seconds']>0)
     write(out,r);print('E2',rid,mode,qkey,r['feasible'],round(r['elapsed_seconds'],3),flush=True)
    if r['feasible'] and r.get('decisions'):
     plan=r['decisions'];score=problem.engine.verify(plan);assert score['admissible']
     p=prefix_of(score['objective'],case['reference']['objective']);ms,us=changes(plan,problem.origin)
     cache.add_witness(p,us,len(ms),plan,str(out.relative_to(ROOT)))
    elif r['feasible'] is False:cache.add_exclusion(q,str(out.relative_to(ROOT)))
    records.append({k:v for k,v in r.items() if k not in ('decisions','rejected_candidates')})
   write(done,{'record_id':rid,'mode':mode,'wall_seconds':time.perf_counter()-started,'seed_validation_seconds':seed_validation,
    'preparation_seconds':problem.preparation_seconds,'inference_seconds':cache.inference_seconds,'queries':len(records),
    'solver_calls':sum(r['direct_solver_called'] for r in records),'known':sum(r['feasible'] is not None for r in records),
    'query_elapsed_seconds':sum(r['elapsed_seconds'] for r in records),'records':records})
 summarize()

def summarize():
 out=[];queryrows=[];method=[]
 for case in load_cases():
  folder=ROOT/'runs'/'e2'/case['record_id'];candidates,queries=context(case)
  for mode in ('direct_static','cross_query_reuse'):
   path=folder/f'{mode}_complete.json'
   if path.exists():method.append({k:v for k,v in read(path).items() if k!='records'})
  results={}
  for qkey,spec in queries.items():
   candidates_results=[]
   for mode in ('direct_static','cross_query_reuse'):
    path=folder/mode/(qkey+'.json')
    if path.exists():
     r=read(path);candidates_results.append(r)
     queryrows.append({'record_id':case['record_id'],'group':case['group'],'mode':mode,'key':qkey,**spec,'feasible':r['feasible'],'evidence':r['evidence'],'seconds':r['elapsed_seconds'],'solver_seconds':r['solver_seconds'],'source_file':str(path.relative_to(ROOT))})
   definite=[r['feasible'] for r in candidates_results if r['feasible'] is not None]
   assert len(set(definite))<=1,(case['record_id'],qkey,'contradictory variants')
   results[qkey]=definite[0] if definite else None
  for c in candidates:
   if 'queries' in c:
    values={name:results.get(qkey) for name,qkey in c['queries'].items()};c.update(values)
    support,budget=values['T6_support'],values['T6_budget']
    c['diagnosis']='support_insufficient' if support is False else 'support_sufficient_budget_insufficient' if support and budget is False else 'support_and_budget_sufficient' if budget else 'support_sufficient_budget_unknown' if support else 'unresolved'
    c['single_reference_false_insufficiency']=bool(support and not c['single_reference_fits_support'])
   out.append(c)
 write(ROOT/'analysis'/'e2_candidate_diagnoses.json',out);write(ROOT/'analysis'/'e2_query_results.json',queryrows);write(ROOT/'analysis'/'e2_computation.json',method)
 for name,rows in [('e2_candidate_diagnoses',out),('e2_query_results',queryrows),('e2_computation',method)]:
  if not rows:continue
  fields=list(dict.fromkeys(k for r in rows for k in r))
  with (ROOT/'analysis'/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
   for r in rows:w.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})
 summary={g:{s:dict(Counter(r.get('diagnosis','excluded') for r in out if r['group']==g and r['source']==s)) for s in SOURCES} for g in ('original','paired')}
 write(ROOT/'analysis'/'e2_summary.json',summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','summarize']);p.add_argument('--seconds',type=float,default=30);p.add_argument('--only',nargs='*');a=p.parse_args()
 if a.mode=='run':run(a.seconds,a.only)
 else:summarize()
