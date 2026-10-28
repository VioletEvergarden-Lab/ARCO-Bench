"""Independent replay and compact evidence exports; no reference-fed search."""
import csv,json,collections,statistics
from run_deterministic import ROOT,read,write,digest,ce,CoordinationProblem,changes,target_met

def csvwrite(path,rows):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
 manifest=read(ROOT/'instances/FROZEN.json');panel=read(ROOT/'analysis/scope_panel.json');methods=[];cases=[];local=[]
 for item in manifest['tasks']:
  rid=item['record_id'];task=read(ROOT/item['task_path']);engine=ce.Engine(task)
  ref=read(ROOT/'runs/deterministic'/f'{rid}__Full-MILP.json');assert ref['global_optimal']
  g=read(ROOT/'runs/deterministic'/f'{rid}__G.json')
  saved_g=read(ROOT/'runs/origins'/f'{rid}.json');assert g['decisions']==saved_g['decisions']
  for method in ['G','R4','R_frac','Iter-R4','Full-MILP']:
   r=read(ROOT/'runs/deterministic'/f'{rid}__{method}.json');v=engine.verify(r['decisions'])
   assert v['admissible'] and ce.compare(v['objective'],r['objective'])==0
   hit=ce.quality(v['objective'],ref['objective'])
   assert ce.compare(v['objective'],ref['objective'])>=0
   row=dict(record_id=rid,condition=item['condition'],method=method,missions=item['missions'],served=int(item['missions']-v['objective']['total_holds']),quality_hit=hit,seconds=r['total_seconds'],global_optimal=r['global_optimal'],reused_from=r.get('reused_from',''))
   row.update(v['objective']);methods.append(row)
   if method in ['R4','Iter-R4'] and not hit:
    n=r['neighborhoods'][-1];out=ROOT/'runs/local_diagnostics'/f'{rid}__{method}.json'
    cp=CoordinationProblem(task,n['center_decisions'],origin_name=method+'_actual_last_center')
    q=read(out) if out.exists() else cp.solve(ref['objective'],target_prefix=6,minimize='feasibility',task_budget=n['radius'],seconds=60.,witness=ref['decisions'])
    write(out,q);local.append(dict(record_id=rid,method=method,radius=n['radius'],status=q['status'],category='target_excluded' if q['status']=='infeasible' else 'target_inside' if q['feasible'] else 'unresolved',path=out.relative_to(ROOT).as_posix()))
  target6=[x for x in panel['rows'] if x['record_id']==rid and x['target']=='T6']
  pair=next(x for x in panel['joint_frontiers'] if x['record_id']==rid and x['target']=='T6')['verified_pareto_pairs']
  cases.append(dict(record_id=rid,base_id=item['base_id'],condition=item['condition'],missions=item['missions'],G=g['objective'],reference=ref['objective'],G_quality=ce.quality(g['objective'],ref['objective']),T6_missions=next(x['upper'] for x in target6 if x['metric']=='missions'),T6_chains=next(x['upper'] for x in target6 if x['metric']=='chains'),T6_joint=pair))
 csvwrite(ROOT/'analysis/deterministic_results.csv',methods)
 counts={m:dict(N=15,admissible=15,quality=sum(r['quality_hit'] for r in methods if r['method']==m),median_seconds=statistics.median(r['seconds'] for r in methods if r['method']==m),max_seconds=max(r['seconds'] for r in methods if r['method']==m)) for m in ['G','R4','R_frac','Iter-R4','Full-MILP']}
 out=dict(status='PASS',conditions=15,formal_unique_records=36,mission_occurrences=108,methods=counts,cases=cases,local_diagnostics=local,scalar_positions=len(panel['rows']),scalar_exact=sum(x['status']=='optimal' for x in panel['rows']),joint_frontiers=len(panel['joint_frontiers']))
 write(ROOT/'analysis/deterministic_summary.json',out)
 print(json.dumps(counts,indent=2));print('local',collections.Counter(x['category'] for x in local))
 event_rows=[]
 for rid in ['ADDS_PACZ05_N09__CLOSE_2MIN','ADDS_PACZ04_N06__CLOSE_5MIN']:
  item=next(x for x in manifest['tasks'] if x['record_id']==rid);task=read(ROOT/item['task_path']);engine=ce.Engine(task)
  origin=read(ROOT/'runs/deterministic'/f'{rid}__G.json');witness=read(ROOT/'runs/coordination'/f'{rid}__T6__missions.json')
  t3=read(ROOT/'runs/coordination'/f'{rid}__T3__missions.json')
  plans={'G':origin['decisions'],'T3_witness':t3['decisions'],'scope_witness':witness['decisions']}
  reconstruct={name:engine.verify(plan) for name,plan in plans.items()}
  calendars={}
  for name,plan in plans.items():
   events=reconstruct[name]['events'];moves=[]
   for e in events:
    if e['held']:continue
    moves+=[dict(mission=e['mission_id'],uav=e['uav_id'],type='departure',time=e['depart_min'],bucket=int(e['depart_min']//1)),dict(mission=e['mission_id'],uav=e['uav_id'],type='return',time=e['return_arrival_min'],bucket=int(e['return_arrival_min']//1))]
    event_rows.append(dict(record_id=rid,plan=name,mission_id=e['mission_id'],uav=e['uav_id'],depart_min=e['depart_min'],delivery_arrival_min=e['arrival_min'],return_start_min=e['return_start_min'],return_arrival_min=e['return_arrival_min'],loading_start_min=e['loading_start_min'],due_min=next(m['due_min'] for m in task['missions'] if m['mission_id']==e['mission_id']),tardiness_min=e['tardiness_min'],remaining_soc=e['soc_after_return_kwh']))
   calendars[name]=dict(movements=sorted(moves,key=lambda x:(x['time'],x['type'],x['mission'])),occupancy=dict(sorted(collections.Counter(x['bucket'] for x in moves).items())))
  write(ROOT/'analysis/events'/f'{rid}.json',dict(record_id=rid,task_path=item['task_path'],origin='G',target='T6',minimum_mission_changes=witness['upper_bound'],changed_missions=witness['changed_missions'],changed_uavs=witness['changed_uavs'],verified_plans=reconstruct,decisions=plans,hub_calendars=calendars))
 csvwrite(ROOT/'analysis/event_comparison.csv',event_rows)
if __name__=='__main__':main()
