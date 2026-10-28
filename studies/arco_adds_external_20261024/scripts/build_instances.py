"""Build ADDS complete-sortie snapshots from the input-only selection.

Incumbents use earliest feasible departures in fixed wave/UAV order, without
references, repair queries or generated candidates. No formal freeze is written
here: the design pilot and runtime checks precede the separate freeze command.
"""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import argparse,copy,hashlib,json,math,sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
from adds_runtime import load_runtime
ce,CoordinationProblem,changes,target_met,MODEL=load_runtime()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def incumbent(engine):
 options=engine.options();calendar=Counter();out=[]
 states={u:dict(clock=v['available_min'],soc=engine.initial[u]) for u,v in engine.fleet.items()}
 for m in sorted(engine.missions.values(),key=lambda m:(m['sequence_index'],m['uav_id'])):
  mid=m['mission_id'];state=states[m['uav_id']];u=engine.fleet[m['uav_id']]
  legal=[o for o in options[mid] if o['start_min']>=state['clock']-ce.EPS_TIME
   and state['soc']-o['energy_kwh']>=u['reserve_kwh']-ce.SOC_TOL
   and all(calendar[k]+n<=engine.capacity(k) for k,n in o['blocks'].items())]
  if not legal:raise ValueError(('Source-selected incumbent infeasible',engine.task['record_id'],mid))
  o=min(legal,key=lambda o:(o['depart_min'],o['path_id']))
  out.append({k:o[k] for k in ('mission_id','uav_id','held','path_id','depart_min','charge_blocks')})
  calendar.update(o['blocks']);state.update(clock=o['finish_min'],soc=state['soc']-o['energy_kwh'])
 return sorted(out,key=lambda d:d['mission_id'])

def make_base(wave,grid=0.5,hub_capacity=2):
 rows=wave['source_rows'];hub=wave['locker_id'];n_u=wave['uavs']
 xy={hub:[0.,0.]}
 for r in rows:xy[r['building_id']]=[(float(r['building_x'])-float(r['locker_x']))/1000,(float(r['building_y'])-float(r['locker_y']))/1000]
 paths={};corridors=[]
 for building in sorted(set(xy)-{hub}):
  for src,dst in ((hub,building),(building,hub)):
   cid=f'C_{src}_{dst}'
   corridors.append(dict(corridor_id=cid,origin=src,destination=dst,distance_km=math.dist(xy[src],xy[dst]),geometry_xy_km=[xy[src],xy[dst]]))
   paths[src,dst]=dict(path_id='DIRECT',origin=src,destination=dst,corridor_ids=[cid])
 task=dict(record_id=wave['base_id'],schema_version='arco_continuous_events_v1',
  adaptation='ADDS complete fixed delivery sortie: loaded service, fixed empty return',
  model=copy.deepcopy(MODEL),timing=dict(departure_grid_min=grid,resource_window_min=1,pad_window_min=1,
     charge_block_min=5,max_charge_blocks=0,turnaround_min=0,load_min=5/60,unload_min=5/60,horizon_departure_min=120),
  nodes=[dict(vertiport_id=k,xy_km=v) for k,v in xy.items()],corridors=corridors,
  fleet=[dict(uav_id=f'U{i+1:02d}',initial_soc_kwh=MODEL['initial_fraction']*MODEL['battery_capacity_kwh'],
    battery_capacity_kwh=MODEL['battery_capacity_kwh'],reserve_kwh=MODEL['reserve_fraction']*MODEL['battery_capacity_kwh'],
    available_min=0,initial_vertiport=hub) for i in range(n_u)],
  missions=[],resources=dict(corridor={c['corridor_id']:n_u for c in corridors},
    pad={node:(hub_capacity if node==hub else 2*n_u) for node in xy},charger={node:0 for node in xy}),
  baseline=dict(decisions=[]),intervention=dict(resource_intervals=[],initial_soc_overrides={}),
  source_context=dict(dataset='ADDS v1.0',city_case='Katowice',locker_id=hub,base_id=wave['base_id'],
    geometry='Saved simulation model geometry in metres; translated to a local kilometre frame; not map-registered',
    demand='Generated workbook records, not observed UAV deliveries',
    parcel_availability='Selected parcels available at the locker at t=0',
    dispatch='Three fixed chains assigned round-robin in source workbook order',
    resource='Hub capacity is the declared count of takeoff/landing reservations per one-minute window, not locker storage capacity',
    return_policy='Return begins immediately after recipient unloading; every executed task returns to the same hub'))
 for a,r in zip(wave['assignment'],rows):
  m=dict(mission_id=a['mission_id'],uav_id=a['uav_id'],sequence_index=a['sequence_index'],origin=hub,destination=r['building_id'],
   payload_kg=float(r['weight_kg']),priority='routine',release_min=0,due_min=120,
   paths=[copy.deepcopy(paths[hub,r['building_id']])],incoming=None,return_path=copy.deepcopy(paths[r['building_id'],hub]),
   source_demand_excel_row=int(r['demand_excel_row']),source_demand_id=int(r['demand_id']))
  task['missions'].append(m)
  task['baseline']['decisions'].append(dict(mission_id=m['mission_id'],uav_id=m['uav_id'],held=False,path_id='DIRECT',depart_min=0,charge_blocks=0))
 task['baseline']['decisions']=incumbent(ce.Engine(task))
 initial=ce.Engine(task).verify(task['baseline']['decisions'])
 assert initial['admissible'],initial['errors']
 by={e['mission_id']:e for e in initial['events']}
 for m in task['missions']:m['due_min']=by[m['mission_id']]['arrival_min']+3
 task['timing']['horizon_departure_min']=math.ceil(max(d['depart_min'] for d in task['baseline']['decisions']))+8
 check=ce.Engine(task).verify(task['baseline']['decisions'])
 assert check['admissible'] and check['objective']['total_holds']==0
 return task,check

def add_condition(base,name):
 task=copy.deepcopy(base);task['record_id']=base['record_id']+'__'+name
 if name!='CONTROL':
  duration={'CLOSE_2MIN':2,'CLOSE_5MIN':5}[name]
  task['intervention']['resource_intervals']=[dict(kind='pad',resource=base['source_context']['locker_id'],start_min=0,end_min=duration,capacity=0)]
 return task

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--development',action='store_true');args=parser.parse_args()
 if (ROOT/'instances/FROZEN.json').exists():raise RuntimeError('Formal instances are frozen; construction cannot overwrite them')
 select=read(ROOT/'analysis/input_selection.json')
 if args.development:
  wave=copy.deepcopy(next(w for w in select['waves'] if w['locker_id']=='PACZ_05'))
  wave['source_rows']=wave['source_rows'][:6];wave['assignment']=wave['assignment'][:6]
  wave.update(missions=6,chain_length=2,base_id='DEV_PACZ05_N06')
  base,check=make_base(wave,grid=1)
  out=ROOT/'runs/design_pilot';write(out/'coarse_incumbent_task.json',base);write(out/'incumbent_verification.json',check)
  coarse=add_condition(base,'CLOSE_5MIN');fine=copy.deepcopy(coarse);fine['record_id']=coarse['record_id']+'__GRID05';fine['timing']['departure_grid_min']=.5
  write(out/'grid1_task.json',coarse);write(out/'grid05_task.json',fine)
  print(json.dumps(dict(stage='development',missions=6,incumbent_horizon=base['timing']['horizon_departure_min'],incumbent=check['objective']),indent=2));return
 manifest=[]
 for wave in select['waves']:
  base,score=make_base(wave)
  write(ROOT/'instances/bases'/f"{wave['base_id']}.json",base)
  write(ROOT/'runs/incumbents'/f"{wave['base_id']}.json",score)
  for condition in ('CONTROL','CLOSE_2MIN','CLOSE_5MIN'):
   task=add_condition(base,condition);path=ROOT/'instances/tasks'/f"{task['record_id']}.json";write(path,task)
   g=ce.Engine(task).greedy();verified=ce.Engine(task).verify(g);assert verified['admissible']
   write(ROOT/'runs/origins'/f"{task['record_id']}.json",dict(decisions=g,verification=verified))
   manifest.append(dict(record_id=task['record_id'],base_id=wave['base_id'],locker_id=wave['locker_id'],condition=condition,
    task_path=path.relative_to(ROOT).as_posix(),sha256=digest(path),missions=wave['missions'],uavs=wave['uavs'],
    horizon_departure_min=task['timing']['horizon_departure_min'],G_objective=verified['objective']))
 write(ROOT/'instances/DESIGN.json',dict(created_utc=datetime.now(timezone.utc).isoformat(),frozen=False,adopted_hub_movement_capacity_per_minute=2,
  source_selection_sha256=digest(ROOT/'analysis/input_selection.json'),tasks=manifest))
 print(json.dumps(dict(bases=5,conditions=len(manifest),rows=[(r['record_id'],r['horizon_departure_min'],r['G_objective']['total_holds']) for r in manifest]),indent=2))
if __name__=='__main__':main()
