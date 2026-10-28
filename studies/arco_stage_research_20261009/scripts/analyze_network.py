"""Focused offline network diagnostics from stored candidates and solve traces.
Reads six existing tasks; no solve, provider request, or historical write.
M01-B is reverified, with two single-edit event checks at its fixed schedule.
"""
from pathlib import Path
import copy,csv,json,sys
from collections import Counter
sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[1];WORK=BASE.parent
OLD=WORK/'arco_closing_study';FOCUS=WORK/'arco_focused_revision_20261002'
sys.path.insert(0,str(OLD))
from continuous_engine import Engine,quality,compare,TIERS,QUALITY_TOL
IDS=('NET_S02_C','NET_M01_B','NET_M01_C','NET_M03_B','NET_L02_B','NET_L02_C')
FIELDS=('held','path_id','depart_min','charge_blocks')
METHODS=('G','R4','Iter-R4','R_frac','Full-MILP')
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def rel(p):return p.relative_to(WORK).as_posix()
def index(ds):return {d['mission_id']:d for d in ds}
def changes(ds,base):
 if ds is None:return None,None
 b=index(base);changed=[d['mission_id'] for d in ds if any(d[k]!=b[d['mission_id']][k] for k in FIELDS)]
 return sorted(changed),sorted({d['uav_id'] for d in ds if d['mission_id'] in changed})
def csvout(p,data):
 keys=list(dict.fromkeys(k for r in data for k in r))
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
  for r in data:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})

def main():
 scores=read(OLD/'evaluation/scores.json');models={(s['record_id'],s['source']):s for s in scores if s['source'] in ('deepseek','luna')}
 oldmetrics={(r['record_id'],r['source']):r for r in rows(OLD/'evaluation/per_task.csv')}
 current={(r['record_id'],r['method']):r for r in rows(FOCUS/'results/comparison/per_task.csv')}
 bounds={r['record_id']:r for r in read(OLD/'coordination_bounds/results.json')}
 chains={r['record_id']:r for r in read(FOCUS/'results/mechanism/cross_chain_necessity.json')}
 out=[];plans={};tasks={};proofs={}
 for rid in IDS:
  task=read(OLD/'networks/tasks'/f'{rid}.json');tasks[rid]=task
  old=read(OLD/'networks/candidates'/f'{rid}.json');reference=read(OLD/'networks/references'/f'{rid}.json')
  g=old['G']['decisions'];target=reference['objective'];proof=old['R4']['result']
  for source in ('reference',*METHODS,'deepseek','luna'):
   run=None;terminal=None;status='admissible';admissible=True;online=None;response=None;src=''
   if source=='reference':
    ds=reference['decisions'];obj=target;src=rel(OLD/'networks/references'/f'{rid}.json')
   elif source in METHODS:
    path=FOCUS/'results/comparison/runs'/f'{rid}__{source}.json';run=read(path)
    ds=run['decisions'];obj=run['objective'];admissible=run['admissible'];status=run['stop_reason'];src=rel(path)
    value=current[rid,source]['first_reference_quality_seconds'];online=float(value) if value else None
   else:
    score=models[rid,source];ds=score.get('decisions');obj=score.get('objective');status=score['status'];admissible=score['admissible']
    path=OLD/'online'/source/'attempts'/rid/'TERMINAL.json';terminal=read(path)
    response=terminal.get('latency_seconds');src=rel(path)+' | '+rel(OLD/'evaluation/scores.json')
   plans[rid,source]=ds
   changed,uavs=changes(ds,g);refchanged,refuavs=changes(ds,reference['decisions'])
   match=bool(admissible and obj and quality(obj,target))
   first=next((i for i,(k,tol) in enumerate(zip(TIERS,QUALITY_TOL)) if obj and abs(obj[k]-target[k])>tol+1e-10),None)
   last=run['neighborhoods'][-1] if run and run['neighborhoods'] else None
   row={'record_id':rid,'candidate_source':source,'candidate_status':status,'admissible':admissible,
    'optimal_service':bool(admissible and obj and all(abs(obj[k]-target[k])<1e-9 for k in TIERS[:2])),
    'reference_quality':match,'first_miss_tier':f'L{first+1}' if first is not None else None,
    'first_gap':obj[TIERS[first]]-target[TIERS[first]] if first is not None else None,
    **{f'L{i+1}':obj[k] if obj else None for i,k in enumerate(TIERS)},
    'distance_origin':'G','changed_missions_vs_G':changed,'changed_count_vs_G':len(changed) if changed is not None else None,
    'changed_chains_vs_G':uavs,'changed_chain_count_vs_G':len(uavs) if uavs is not None else None,
    'changed_missions_vs_reference':refchanged,'distance_to_recorded_reference':len(refchanged) if refchanged is not None else None,
    'quality_distance_lower_bound':bounds[rid]['distance_lower_bound'] or None,'quality_distance_upper_bound':bounds[rid]['distance_upper_bound'],
    'necessary_changed_chains_lower_bound':chains.get(rid,{}).get('necessary_minimum_changed_chains'),
    'exact_minimum_changed_chains':chains.get(rid,{}).get('exact_minimum_changed_chains'),
    'historical_radius4_proved_prefix':proof['proved_prefix'],
    'online_radius':run.get('radius') if run else None,'online_final_neighborhood':last['index'] if last else None,
    'online_final_proved_prefix':last['proved_prefix'] if last else None,
    'online_last_stage_status':run['phases'][-1]['status'] if run and run['phases'] else None,
    'online_first_reference_quality_seconds':online,'historical_response_terminal_seconds':response,
    'http_status':terminal.get('http_status') if terminal else None,'provider_error':terminal.get('error') if terminal else None,
    'source':src,'distance_source':rel(OLD/'coordination_bounds/results.json'),
    'cross_chain_source':rel(FOCUS/'results/mechanism/cross_chain_necessity.json') if rid in chains else None}
   out.append(row)
  assert changes(plans[rid,'G'],g)[0]==[]
  assert quality(old['R4']['score']['objective'],read(FOCUS/'results/comparison/runs'/f'{rid}__R4.json')['objective'])
 # A stored radius-five witness tightens the old M01-C bound without solving.
 rid='NET_M01_C';engine=Engine(tasks[rid]);witness=plans[rid,'R_frac']
 check=engine.verify(witness);reference=read(OLD/'networks/references'/f'{rid}.json')
 old=read(OLD/'networks/candidates'/f'{rid}.json');g=old['G']['decisions']
 changed,uavs=changes(witness,g)
 assert check['admissible'] and quality(check['objective'],reference['objective'])
 assert check['objective']==reference['objective'] and len(changed)==5 and len(uavs)==3
 assert bounds[rid]['distance_lower_bound']==5
 source=FOCUS/'results/comparison/runs'/f'{rid}__R_frac.json';run=read(source)
 assert run['neighborhoods'][0]['center_decisions']==g and run['radius']==5
 witness_check={'record_id':rid,'source':rel(source),'verifier':rel(OLD/'continuous_engine.py')+'::Engine.verify',
  'admissible':check['admissible'],'errors':check['errors'],'reference_quality':True,
  'objective':check['objective'],'reference_objective':reference['objective'],
  'changed_missions_vs_G':changed,'changed_chains_vs_G':uavs,'quality_distance_lower_bound':5,
  'quality_distance_upper_bound':5,'exact_minimum_changed_missions':5,'chain_count_bounds':[2,3],
  'center_equals_historical_G':True,'decisions':witness,
  'changed_decisions':[{'mission_id':mid,'before':index(g)[mid],'after':index(witness)[mid]} for mid in changed]}
 strengthened=[]
 for target_id,radius,lower,upper in [('NET_L02_C',8,9,9),('NET_M03_B',5,6,7)]:
  path=FOCUS/'results/comparison/runs'/f'{target_id}__R_frac.json';local=read(path)
  original=read(OLD/'networks/candidates'/f'{target_id}.json');g0=original['G']['decisions']
  reference=read(OLD/'networks/references'/f'{target_id}.json');engine=Engine(tasks[target_id])
  witness_score=engine.verify(reference['decisions']);local_score=engine.verify(local['decisions'])
  assert local['radius']==radius and local['neighborhoods'][0]['center_decisions']==g0
  assert local['neighborhoods'][0]['proved_prefix']==6 and all(p['proved'] for p in local['phases'])
  assert witness_score['admissible'] and quality(witness_score['objective'],reference['objective'])
  assert local_score['admissible']
  phases={p['tier']:p for p in local['phases']}
  assert all(local_score['objective'][k]==reference['objective'][k] for k in TIERS[:2])
  phase=phases['repair_distance']
  assert phase['lower_bound']==phase['upper_bound'] and phase['lower_bound']>reference['objective']['repair_distance']+QUALITY_TOL[2]
  changed,changed_chains=changes(reference['decisions'],g0);assert len(changed)==upper
  strengthened.append({'record_id':target_id,'source':rel(path),'radius':radius,'center_equals_historical_G':True,
   'proved_prefix':6,'service_prefix':[local_score['objective'][k] for k in TIERS[:2]],
   'local_L3_lower_bound':phase['lower_bound'],'local_L3_upper_bound':phase['upper_bound'],
   'reference_objective':reference['objective'],'witness_admissible':witness_score['admissible'],'witness_errors':witness_score['errors'],
   'witness_reference_quality':True,'witness_source':rel(OLD/'networks/references'/f'{target_id}.json'),
   'witness_changed_missions':changed,'witness_changed_chains':changed_chains,
   'quality_distance_lower_bound':lower,'quality_distance_upper_bound':upper,
   'exact_minimum_changed_missions':lower if lower==upper else None,'first_three_proof_phases':local['phases'][:3]})
 for row in out:
  row['historical_quality_distance_lower_bound']=row['quality_distance_lower_bound']
  row['historical_quality_distance_upper_bound']=row['quality_distance_upper_bound']
  row['current_quality_distance_witness_source']=row['distance_source']
  if row['record_id']==rid:
   row['quality_distance_upper_bound']=5
   row['current_quality_distance_witness_source']=rel(source)
  row['current_quality_distance_proof_source']=row['distance_source']
  for bound in strengthened:
   if row['record_id']==bound['record_id']:
    row['quality_distance_lower_bound']=bound['quality_distance_lower_bound']
    row['current_quality_distance_proof_source']=bound['source']
    max_chain=max(Counter(m['uav_id'] for m in tasks[row['record_id']]['missions']).values())
    row['necessary_changed_chains_lower_bound']=(bound['quality_distance_lower_bound']+max_chain-1)//max_chain
  lo,hi=row['quality_distance_lower_bound'],row['quality_distance_upper_bound']
  row['exact_minimum_changed_missions']=lo if lo is not None and lo==hi else None
  witnesses=[r for r in out if r['record_id']==row['record_id'] and r['reference_quality']]
  row['current_changed_chains_upper_bound']=min(r['changed_chain_count_vs_G'] for r in witnesses)
 # Read all current miss statuses, without rerunning their solver or evaluator.
 miss_status={}
 for method in ('Iter-R4','R_frac'):
  records=[]
  for (rid,m),r in current.items():
   if m!=method or r['reference_quality']!='False':continue
   p=FOCUS/'results/comparison/runs'/f'{rid}__{method}.json';run=read(p);last=run['neighborhoods'][-1]
   records.append({'record_id':rid,'last_prefix':last['proved_prefix'],'stop':run['stop_reason'],'last_center':last['center_objective'],'radius':run['radius']})
  miss_status[method]=records
 assert sum(r['last_prefix']==6 for r in miss_status['Iter-R4'])==1 and len(miss_status['Iter-R4'])==7
 assert len(miss_status['R_frac'])==8 and all(r['last_prefix']==6 for r in miss_status['R_frac'])
 # Necessary fixed-plan event reconstruction only; no changed model or optimization.
 rid='NET_M01_B';eng=Engine(tasks[rid]);case={}
 for source in ('G','R4','deepseek','luna'):
  score=eng.verify(plans[rid,source]);assert score['admissible']
  existing=next(r for r in out if r['record_id']==rid and r['candidate_source']==source)
  assert all(abs(score['objective'][k]-existing[f'L{i+1}'])<1e-8 for i,k in enumerate(TIERS))
  case[source]={'objective':score['objective'],'events':[e for e in score['events'] if e['mission_id'] in ('M004','M005','M006','M007','M008','M009')],
   'charger_intervals':[e for e in score['resource_intervals'] if e['kind']=='charger']}
 counterfactual=[]
 for mid,count in [('M004',2),('M006',2)]:
  ds=copy.deepcopy(plans[rid,'deepseek']);next(d for d in ds if d['mission_id']==mid)['charge_blocks']=count
  score=eng.verify(ds)
  counterfactual.append({'edit':f'{mid} charge_blocks={count}; all other DeepSeek decisions fixed',
   'admissible':score['admissible'],'errors':score['errors'],
   'violating_windows':[r for r in score['window_loads'] if r['count']>r['capacity']],
   'reserve_violations':[{'mission_id':e['mission_id'],'reserve_margin_Wh':1000*e['reserve_margin_kwh']} for e in score['events'] if not e['held'] and e['reserve_margin_kwh'] < -1e-6]})
  assert not score['admissible']
 csvout(BASE/'analysis/network_diagnostic_candidates.csv',out)
 payload={'rows':len(out),'miss_status':miss_status,'M01B':case,'fixed_plan_checks':counterfactual,'M01C_tightened_witness':witness_check,'strengthened_distance_bounds':strengthened}
 (BASE/'analysis/network_event_checks.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
 print(json.dumps({'rows':len(out),'M01C_exact_distance':5,'M01C_chain_bounds':[2,3],
  'L02C_exact_distance':9,'M03B_distance_bounds':[6,7],'M01B_replayed_sources':list(case),'fixed_plan_event_checks':len(counterfactual),'new_solves':0,'provider_requests':0},indent=2))
if __name__=='__main__':main()
