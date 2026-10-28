"""Targeted charger interventions: fixed aspirations versus reoptimized quality.

Selection uses pre-disruption charger users, before intervention outcomes. All
outputs are isolated here; inherited Full-MILP reads only the supplied task.
"""
from pathlib import Path
import argparse, copy, json, sys, time
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(WS/'arco_focused_revision_20261002'/'scripts'))
from optimization_online import run_online
from coordination_solver import CoordinationProblem, target_met
OLD=WS/'arco_closing_study';FOCUS=WS/'arco_focused_revision_20261002'

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def prepare():
 records=[]
 for rid in ['NET_M01_B']+[f'NEW_{topo}_{scale}01_long' for topo in ('ladder','regions') for scale in ('S','M','L')]:
  original=rid.startswith('NET_');base=OLD/'networks' if original else FOCUS/'new_networks'
  task=read(base/'tasks'/f'{rid}.json');reference=read(base/'references'/f'{rid}.json')
  g=read(FOCUS/'results'/('comparison' if original else 'new_comparison')/'runs'/f'{rid}__G.json')['decisions']
  users=defaultdict(set);mm={m['mission_id']:m for m in task['missions']}
  for d in task['baseline']['decisions']:
   if not d['held'] and d['charge_blocks']>0:users[mm[d['mission_id']]['destination']].add(d['uav_id'])
  facilities=[v for v,c in task['resources']['charger'].items() if c==1]
  facility='V11' if original else sorted(facilities,key=lambda v:(-len(users[v]),v))[0]
  changed=copy.deepcopy(task);changed['record_id']=f'E3_{rid}_{facility}_plus1';changed['resources']['charger'][facility]+=1
  name=changed['record_id'];folder=ROOT/'runs'/'e3'/name
  write(folder/'task.json',changed)
  write(folder/'original_reference.json',reference)
  write(folder/'origins.json',{'G':g,'incumbent':task['baseline']['decisions']})
  meta={'record_id':rid,'intervention_id':name,'group':'development_original' if original else 'paired_input_selected',
   'facility':facility,'pre_incumbent_charger_users':sorted(users[facility]),'old_capacity':1,'new_capacity':2,
   'selection':'M01-B V11 development mechanism' if original else 'base index01 in each topology/scale; most distinct incumbent charging UAVs, lexicographic tie break',
   'source_task':str((base/'tasks'/f'{rid}.json').relative_to(WS)),
   'folder':str(folder.relative_to(ROOT)),'fixed_origin':'original stored G',
   'fixed_target':'each original reference objective is an upper aspiration bound, with its original tolerance',
   'new_target':'componentwise match to newly optimized reference prefix'}
  write(folder/'selection.json',meta);records.append(meta)
 write(ROOT/'analysis'/'e3_selection.json',records)
 return records

def execute(seconds=60,reference_seconds=600):
 entries=read(ROOT/'analysis'/'e3_selection.json')
 for e in entries:
  folder=ROOT/e['folder'];rp=folder/'new_reference.json'
  if not rp.exists():
   result=run_online(folder/'task.json','Full-MILP',budget=reference_seconds);write(rp,result)
   print(e['record_id'],'new_reference',result['global_optimal'],round(result['total_seconds'],2),flush=True)
  newref=read(rp);oldref=read(folder/'original_reference.json');task=read(folder/'task.json');origins=read(folder/'origins.json')
  problem=CoordinationProblem(task,origins['G'],'original_G')
  for label,ref,mode in [('fixed_aspirations',oldref,'ceiling'),('new_reference',newref,'match')]:
   if label=='new_reference' and not newref['global_optimal']:continue
   for j in (2,6):
    for metric in ('missions','chains'):
     out=folder/f'{label}_j{j}_{metric}.json'
     if out.exists():continue
     seed=[ref['decisions']]
     if target_met(newref['objective'],ref['objective'],j,mode):seed.append(newref['decisions'])
     result=problem.solve(ref['objective'],target_prefix=j,minimize=metric,seconds=seconds,witness=seed,target_mode=mode)
     write(out,result);print(e['record_id'],label,j,metric,result['status'],result['lower_bound'],result['upper_bound'],round(result['elapsed_seconds'],2),flush=True)
 summarize()

def summarize():
 entries=read(ROOT/'analysis'/'e3_selection.json');rows=[]
 for e in entries:
  folder=ROOT/e['folder'];rp=folder/'new_reference.json'
  if not rp.exists():continue
  newref=read(rp);oldref=read(folder/'original_reference.json')
  for p in sorted(folder.glob('*_j*_*.json')):
   r=read(p);rows.append({**e,'query_file':str(p.relative_to(ROOT)),'target_kind':p.name.split('_j')[0],
    'target_prefix':r['target_prefix'],'metric':r['minimize'],'lower_bound':r['lower_bound'],'upper_bound':r['upper_bound'],
    'status':r['status'],'seconds':r['elapsed_seconds'],'changed_uavs':r['changed_uavs'],
    'new_reference_proved':newref['global_optimal'],'new_reference_seconds':newref['total_seconds'],
    'original_objective':oldref['objective'],'new_objective':newref['objective']})
 write(ROOT/'analysis'/'e3_interventions.json',rows)
 import csv
 if rows:
  with (ROOT/'analysis'/'e3_interventions.csv').open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
   for r in rows:w.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()})
 print('E3 rows',len(rows),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','run','summarize']);p.add_argument('--seconds',type=float,default=60);p.add_argument('--reference-seconds',type=float,default=600);a=p.parse_args()
 if a.mode=='prepare':prepare()
 elif a.mode=='run':execute(a.seconds,a.reference_seconds)
 else:summarize()
