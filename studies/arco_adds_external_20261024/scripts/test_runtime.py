"""Targeted regressions for the ADDS optional sortie adapter and fine grids.

Small synthetic cases isolate timing, energy and query behavior. A preserved
six-task pilot checks the legacy branch against the original implementation.
No models are called and no historical files are changed.
"""
from pathlib import Path
import copy,hashlib,itertools,json,math,time
from adds_runtime import load_runtime,ROOT
ce,CP,changes,target_met,MODEL=load_runtime()
import base_engine
OUT=ROOT/'runs/runtime_regression';OUT.mkdir(parents=True,exist_ok=True)
ce.HERE=OUT;base_engine.HERE=OUT

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def decision(o):return {k:o[k] for k in ('mission_id','uav_id','held','path_id','depart_min','charge_blocks')}
def hold(mid,uid='U01'):return dict(mission_id=mid,uav_id=uid,held=True,path_id=None,depart_min=None,charge_blocks=0)
def toy(grid=.5,n=2,distance=.3,capacity=2):
    t=dict(record_id='RUNTIME_TOY',schema_version='arco_continuous_events_v1',model=copy.deepcopy(MODEL),
           timing=dict(departure_grid_min=grid,resource_window_min=1,pad_window_min=1,charge_block_min=5,
                       max_charge_blocks=0,turnaround_min=5/60,load_min=5/60,unload_min=5/60,horizon_departure_min=8),
           nodes=[dict(vertiport_id='H',xy_km=[0.,0.])],corridors=[],fleet=[dict(uav_id='U01',initial_soc_kwh=.07992,
           battery_capacity_kwh=.0999,reserve_kwh=.01998,available_min=0,initial_vertiport='H')],
           missions=[],resources=dict(corridor={},pad={'H':capacity},charger={'H':0}),baseline=dict(decisions=[]),
           intervention=dict(resource_intervals=[],initial_soc_overrides={}))
    for i in range(n):
        mid=f'M{i+1:03d}';b=f'B{i+1}';xy=[distance,0.]
        t['nodes'].append(dict(vertiport_id=b,xy_km=xy));t['resources']['pad'][b]=4;t['resources']['charger'][b]=0
        for a,z,points in [('H',b,[[0.,0.],xy]),(b,'H',[xy,[0.,0.]])]:
            cid=a+'_'+z;t['corridors'].append(dict(corridor_id=cid,origin=a,destination=z,distance_km=distance,geometry_xy_km=points));t['resources']['corridor'][cid]=2
        path=dict(path_id='DIRECT',origin='H',destination=b,corridor_ids=['H_'+b])
        ret=dict(path_id='RETURN',origin=b,destination='H',corridor_ids=[b+'_H'])
        dep=1+3*i
        t['missions'].append(dict(mission_id=mid,uav_id='U01',sequence_index=i+1,origin='H',destination=b,
               payload_kg=.5,priority='routine',release_min=0,due_min=dep+ce.flight(t,path,.5)['flight_min']+3,
               paths=[path],incoming=None,return_path=ret))
        t['baseline']['decisions'].append(dict(mission_id=mid,uav_id='U01',held=False,path_id='DIRECT',depart_min=dep,charge_blocks=0))
    return t

checks=[];new_solves=0
def record(name,**details):checks.append(dict(name=name,passed=True,**details))
started=time.perf_counter()

# Legacy behavior remains unchanged on an actual six-task archived case.
fixture=ROOT/'runtime/fixtures'
legacy=read(fixture/'legacy_pilot_task.json');old=base_engine.Engine(legacy);adapted=ce.Engine(legacy)
old_g=old.greedy();assert adapted.greedy()==old_g
assert adapted.verify(old_g)==old.verify(old_g)
ref=read(fixture/'legacy_pilot_reference.json')
assert adapted.verify(ref['decisions'])==old.verify(ref['decisions'])
ob,nb=old.build(),adapted.build()
assert (ob['A']!=nb['A']).nnz==0
assert (ob['costs']==nb['costs']).all() and (ob['scales']==nb['scales']).all()
record('archived_six_task_legacy_equivalence',record_id=legacy['record_id'],greedy_and_reference_replays=True,sparse_model_identical=True)

# Direct exhaustive finite-option enumeration checks reference optimality on
# each grid and independently checks its return-energy accounting.
reference_records={}
for grid in (1,.5,.25):
    task=toy(grid);task['record_id']='TOY_GRID_'+str(grid)
    task['intervention']['resource_intervals']=[dict(kind='pad',resource='H',start_min=1,end_min=3,capacity=0)]
    engine=ce.Engine(task);opts=engine.options();best=None;best_plan=None;feasible_count=0
    choices=[[hold(mid)]+[decision(o) for o in opts[mid]] for mid in sorted(engine.missions)]
    for plan in itertools.product(*choices):
        score=engine.verify(list(plan))
        if score['admissible']:
            feasible_count+=1
            if best is None or ce.compare(score['objective'],best)<0:best=score['objective'];best_plan=list(plan)
    result=engine.solve(budget=20);new_solves+=sum('proof' not in p for p in result['phases'])
    assert result['optimal'] and ce.quality(result['objective'],best),(grid,result,best)
    score=engine.verify(result['decisions']);energy=sum(e['service_energy_kwh']+e['return_energy_kwh'] for e in score['events'] if not e['held'])
    assert abs(energy-score['objective']['energy_kwh'])<1e-12
    assert engine.l3_scale==5/grid and engine.pad_width==engine.width==1
    built=engine.build();assert all(abs(x-round(x))<1e-7 for x in built['costs'][2])
    write(OUT/f'grid_{grid}_reference.json',result);reference_records[grid]=(task,result)
    record('reference_vs_exhaustive_grid_'+str(grid),feasible_plans_enumerated=feasible_count,objective=best,l3_scale=engine.l3_scale,resource_window_min=1)

# An isolated half-minute shift has L3=.1; the old scale/round would corrupt it.
task=toy(.5,n=1);engine=ce.Engine(task)
seed=[dict(task['baseline']['decisions'][0],depart_min=1.5)]
forced=engine.solve(seed=seed,k=0,all_served=True,allowed=lambda o:o['depart_min']==1.5,budget=10)
new_solves+=sum('proof' not in p for p in forced['phases'])
assert forced['optimal'] and abs(forced['objective']['repair_distance']-.1)<1e-12
q=CP(task,seed,'late').solve(engine.verify(task['baseline']['decisions'])['objective'],6,'missions',seconds=10,witness=task['baseline']['decisions'])
assert q['optimal'] and q['lower_bound']==q['upper_bound']==1
record('half_minute_L3_prefix_and_scope_query',L3=.1,minimum_changes=1)

# Force a nonzero fractional L3 target through actual scope MILP rows; a warm
# witness with distance two cannot trigger the one-change analytic shortcut.
task=toy(.5);engine=ce.Engine(task)
target_plan=[dict(task['baseline']['decisions'][0],depart_min=1.5),task['baseline']['decisions'][1]]
origin=[dict(task['baseline']['decisions'][0],depart_min=2.5),dict(task['baseline']['decisions'][1],depart_min=5)]
assert engine.verify(origin)['admissible'] and engine.verify(target_plan)['admissible']
target=engine.verify(target_plan)['objective']
q2=CP(task,origin,'late_two').solve(target,6,'missions',seconds=10,witness=target_plan)
assert q2['optimal'] and q2['lower_bound']==q2['upper_bound']==2 and q2['solver_seconds']>0,q2
new_solves+=1;write(OUT/'half_minute_scope_query.json',q2)
record('half_minute_L3_actual_scope_MILP',target_L3=target['repair_distance'],minimum_changes=2)

quarter=toy(.25,n=1);qe=ce.Engine(quarter);qseed=[dict(quarter['baseline']['decisions'][0],depart_min=1.25)]
quarter_ref=qe.solve(seed=qseed,k=0,all_served=True,budget=10)
new_solves+=sum('proof' not in p for p in quarter_ref['phases'])
assert quarter_ref['optimal'] and abs(quarter_ref['objective']['repair_distance']-.05)<1e-12
record('quarter_minute_L3_prefix',L3=.05,l3_scale=20)

# Complete-sortie replay catches suffix/precedence/return-SOC/resource errors.
task=toy(.5);engine=ce.Engine(task);base=task['baseline']['decisions'];assert engine.verify(base)['admissible']
suffix=[base[0],hold('M002')];ss=engine.verify(suffix);assert ss['admissible']
assert len([e for e in ss['events'] if not e['held']])==1 and ss['events'][0]['return_destination']=='H'
assert abs(ss['objective']['energy_kwh']-(engine.info['M001','DIRECT']['energy_kwh']+engine.returns['M001']['energy_kwh']))<1e-12
assert 'SUFFIX_HOLD' in engine.verify([hold('M001'),base[1]])['errors']
too_early=[base[0],dict(base[1],depart_min=2.5)]
assert 'CHAIN_TIME' in engine.verify(too_early)['errors']
eout=engine.info['M001','DIRECT']['energy_kwh'];eret=engine.returns['M001']['energy_kwh']
low=copy.deepcopy(task);low['intervention']['initial_soc_overrides']={'U01':.01998+eout+eret/2}
assert 'SOC_RESERVE_AFTER_RETURN' in ce.Engine(low).verify(suffix)['errors']
late_return=copy.deepcopy(task);arrival=engine.verify(suffix)['events'][0]['return_arrival_min']
late_return['intervention']['resource_intervals']=[dict(kind='pad',resource='H',start_min=math.floor(arrival),end_min=math.floor(arrival)+1,capacity=0)]
assert 'PAD_WINDOW_CAPACITY' in ce.Engine(late_return).verify(suffix)['errors']
record('suffix_final_return_precedence_SOC_resource_checks',suffix_return_energy_counted=True)

# Release remains the departure lower bound. Loading may precede it while
# respecting UAV availability and the preceding return.
release_task=toy(.5,n=1);release_task['missions'][0]['release_min']=1
release_task['baseline']['decisions'][0]['depart_min']=1
re=ce.Engine(release_task);assert re.verify(release_task['baseline']['decisions'])['admissible']
assert any(o['depart_min']==1 and o['loading_start_min']<1 for o in re.options()['M001'])
record('release_limits_departure_not_loading')

# A sub-minute round trip at an integer departure may consume two movements
# in the same one-minute locker window; capacity=1 excludes that option.
near=toy(1,n=1,distance=.01,capacity=1);near_engine=ce.Engine(near)
assert near_engine.returns['M001']['flight_min']+near_engine.info['M001','DIRECT']['flight_min']+near['timing']['unload_min']<1
assert near_engine.options()['M001']==[]
near2=copy.deepcopy(near);near2['resources']['pad']['H']=2
assert ce.Engine(near2).verify(near2['baseline']['decisions'])['admissible']
record('same_window_departure_and_return_count_twice',capacity_one_options=0,capacity_two_feasible=True)

# Domains nest while the incumbent and window capacities remain fixed.
coarse=toy(1);fine=copy.deepcopy(coarse);fine['timing']['departure_grid_min']=.5
e1,e2=ce.Engine(coarse),ce.Engine(fine)
for mid,options in e1.options().items():
    fine_by={(o['depart_min'],o['path_id'],o['charge_blocks']):o for o in e2.options()[mid]}
    for option in options:
        other=fine_by[(option['depart_min'],option['path_id'],option['charge_blocks'])]
        assert option==other
record('fixed_problem_nested_grids',coarse_options=sum(map(len,e1.options().values())),fine_options=sum(map(len,e2.options().values())))

# Genuine lex gate: fixed old target can accept a later-tier deterioration
# after an earlier-tier improvement; it is not componentwise ceiling.
target=e2.verify(coarse['baseline']['decisions'])['objective'];origin=[dict(d,depart_min=d['depart_min']+1) for d in coarse['baseline']['decisions']]
assert e2.verify(origin)['admissible']
problem=CP(fine,origin,'late')
lex=problem.solve_lex_threshold(target,'missions',seconds=20,witness=coarse['baseline']['decisions'])
new_solves+=lex['solver_calls']
assert lex['optimal'] and lex['lower_bound']==lex['upper_bound']==2,lex
assert ce.compare(lex['objective'],target)<=0
write(OUT/'fixed_lex_query.json',lex)
broader=dict(target);broader['repair_distance']=target['repair_distance']+.2;broader['weighted_tardiness_min']=-1
lex0=CP(fine,coarse['baseline']['decisions'],'already_lex_better').solve_lex_threshold(broader,seconds=10)
assert lex0['optimal'] and lex0['upper_bound']==0 and lex0['solver_calls']==0
assert not target_met(target,broader,6,'ceiling')
record('fixed_lex_threshold_distinct_from_componentwise',minimum_changes=2,earlier_improvement_accepts_later_deterioration=True)

out=dict(status='PASS',runtime_version=ce.ADDS_RUNTIME_VERSION,checks=checks,check_count=len(checks),
         targeted_solver_calls=new_solves,seconds=time.perf_counter()-started,
         scope='Optional complete sorties, grid semantics, original pilot regression, and valid fixed-lex bounds; no formal evaluation results.',
         base_engine_sha256=hashlib.sha256((ROOT/'runtime/base_engine.py').read_bytes()).hexdigest())
write(ROOT/'analysis/runtime_validation.json',out)
print(json.dumps(dict(status='PASS',checks=len(checks),seconds=out['seconds'],targeted_solver_calls=new_solves)))
