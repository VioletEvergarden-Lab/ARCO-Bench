"""Quality feasibility in the actual final neighborhood of each local-method miss."""
from pathlib import Path
import argparse,csv,hashlib,json,time
from collections import Counter
from coordination_study import load_cases,read,write,canonical,ROOT
from coordination_solver import CoordinationProblem,Engine,changes,target_met,TIERS,QUALITY_TOL
METHODS=('R4','Iter-R4','R_frac')

def saved_proof(run,nh,target):
 phases={p['tier']:p for p in run['phases'] if p.get('neighborhood')==nh['index'] and p.get('proved')}
 prefix=[]
 for i,tier in enumerate(TIERS[:4]):
  p=phases.get(tier)
  if not p or p.get('lower_bound') is None or p.get('upper_bound') is None:return None
  delta=p['lower_bound']-target[tier]
  if delta>QUALITY_TOL[i]+1e-10:
   return dict(kind='saved_actual_center_prefix_exclusion',tier=tier,lower_bound=p['lower_bound'],
    target_value=target[tier],prefix_phases=prefix+[p])
  if abs(delta)>QUALITY_TOL[i]+1e-10 or abs(p['upper_bound']-target[tier])>QUALITY_TOL[i]+1e-10:return None
  prefix.append(p)
 return None

def main(solve=False,seconds=60):
 start=time.perf_counter();e1=read(ROOT/'analysis/e1_results.json');rows=[];details=[]
 cache={};newcalls=0;newseconds=0.;outdir=ROOT/'runs/e2_actual_neighborhoods';outdir.mkdir(exist_ok=True)
 for case in load_cases():
  rid=case['record_id'];task=case['task'];target=case['reference']['objective'];engine=Engine(task)
  e1rows=[x for x in e1 if x['record_id']==rid]
  pool=[dict(source=c['source_path'],decisions=c['decisions']) for c in case['candidates'].values() if c['target6']]
  pool.extend(dict(source='analysis/e1_results.json:'+x.get('witness_source',''),decisions=x['decisions']) for x in e1rows if x.get('decisions'))
  for method in METHODS:
   candidate=case['candidates'][method]
   if candidate['target6']:continue
   run=candidate['run'];nh=run['neighborhoods'][-1];center=nh['center_decisions'];radius=int(nh['radius'])
   eqg=canonical(center)==canonical(case['origins']['G']);key=(rid,canonical(center),radius)
   result=None;proof=None;witness=None
   for p in pool:
    ms,us=changes(p['decisions'],center)
    if len(ms)>radius:continue
    score=engine.verify(p['decisions'])
    if score['admissible'] and target_met(score['objective'],target,6):
     witness=dict(source=p['source'],decisions=p['decisions'],mission_changes=len(ms),changed_missions=ms,
      changed_uavs=us,objective=score['objective'],independent_verification=True)
     result='witness_inside';break
   proof=saved_proof(run,nh,target)
   if proof:
    if witness:raise RuntimeError(('witness/certificate contradiction',rid,method))
    result='proved_scope_excluded';proof['source']=candidate['source_path']
   if result is None and eqg:
    bounds=[x for x in e1rows if x['metric']=='missions' and x['lower_bound']>radius]
    if bounds:
     q=max(bounds,key=lambda x:x['lower_bound']);proof=dict(kind='same_G_distance_bound',
      source='analysis/e1_results.json',target_prefix=q['target_prefix'],lower_bound=q['lower_bound'],
      evidence=q['evidence']);result='proved_scope_excluded'
   cached=False;query_path=None;new=None
   if result is None:
    sig=hashlib.sha256(json.dumps([center,radius],sort_keys=True).encode()).hexdigest()[:12]
    path=outdir/f'{rid}__center_{sig}__R{radius}.json';query_path=str(path.relative_to(ROOT))
    if key in cache:new=cache[key];cached=True
    elif path.exists():new=read(path);cache[key]=new;cached=True
    elif solve:
     problem=CoordinationProblem(task,center,'actual_final_search_center')
     new=problem.solve(target,target_prefix=6,minimize='feasibility',task_budget=radius,seconds=seconds)
     new.update(source_run=candidate['source_path'],source_neighborhood_index=nh['index'])
     write(path,new);cache[key]=new;newcalls+=1;newseconds+=new['elapsed_seconds']
     print(rid,method,new['status'],round(new['elapsed_seconds'],3),flush=True)
    if new is not None:
     if new['feasible'] is True:
      result='witness_inside';witness=dict(source=query_path,decisions=new['decisions'],
       mission_changes=new['mission_changes'],changed_missions=new['changed_missions'],changed_uavs=new['changed_uavs'],
       objective=new['objective'],independent_verification=new['independent_verification'])
     elif new['feasible'] is False:
      result='proved_scope_excluded';proof=dict(kind='new_actual_neighborhood_infeasibility',source=query_path,
       solver_status=new['solver_status'])
   if result is None:result='unknown'
   row=dict(record_id=rid,group=case['group'],network_id=case['network_id'],method=method,
    source_run=candidate['source_path'],radius=radius,final_neighborhood_index=nh['index'],
    number_of_neighborhoods=len(run['neighborhoods']),center_equals_G=eqg,
    center_changes_from_G=len(changes(center,case['origins']['G'])[0]),
    old_stop_reason=run['stop_reason'],old_final_proved_prefix=nh['proved_prefix'],
    old_final_neighborhood_seconds=nh['end_seconds']-nh['start_seconds'],
    classification=result,evidence_kind=proof['kind'] if proof else 'verified_stored_or_new_witness' if witness else 'unresolved',
    evidence_source=proof.get('source') if proof else witness['source'] if witness else query_path,
    new_query_source=query_path,new_query_status=new['status'] if new else None,
    new_query_seconds=new['elapsed_seconds'] if new else 0,shared_query_reuse=cached,
    witness_distance=witness['mission_changes'] if witness else None,
    conclusion_scope='final actual center and radius only')
   rows.append(row);details.append(dict(**row,center_decisions=center,proof=proof,witness=witness))
  write(ROOT/'analysis/e2_actual_neighborhoods.json',dict(rows=rows,details=details,complete=False))
 summary=dict(misses=len(rows),classification_counts=dict(Counter(r['classification'] for r in rows)),
  by_method={m:dict(Counter(r['classification'] for r in rows if r['method']==m)) for m in METHODS},
  new_calls_this_invocation=newcalls,new_query_seconds_this_invocation=newseconds,
  unique_new_query_files=len({r['new_query_source'] for r in rows if r['new_query_status'] is not None}),
  elapsed_seconds=time.perf_counter()-start,all_60_conditions_screened=True)
 write(ROOT/'analysis/e2_actual_neighborhoods.json',dict(rows=rows,details=details,summary=summary,complete=True))
 with (ROOT/'analysis/e2_actual_neighborhoods.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 print(json.dumps(summary),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--solve',action='store_true');p.add_argument('--seconds',type=float,default=60)
 a=p.parse_args();main(a.solve,a.seconds)
