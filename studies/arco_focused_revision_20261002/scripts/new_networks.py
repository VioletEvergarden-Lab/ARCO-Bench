"""Prespecified dispersed-facility networks and paired corridor closures.

No solver result enters instance acceptance. Historical modules are read-only.
"""
from pathlib import Path
import argparse, copy, hashlib, itertools, json, math, random, sys, time
from collections import Counter

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'arco_closing_study'
sys.path.insert(0,str(OLD))
import study_common
from study_common import read,write,csvout
import continuous_engine as ce
from continuous_engine import Engine,flight,window_cap,SOC_TOL
from physical_model import MODEL
import networkx as nx
ce.HERE=ROOT/'results/new_reference_progress'
OUT=ROOT/'new_networks'

CONFIG={
 'version':'dispersed_pair_v1',
 'topologies':['ladder','regions'],
 'scales':{'S':{'nodes':7,'chains':[2,3,4]},'M':{'nodes':11,'chains':[3,4,4,4,5]},'L':{'nodes':16,'chains':[3,3,4,4,4,4,5,5]}},
 'development_cells':[['ladder','S',81001],['regions','S',81002],['ladder','M',81003],['regions','M',81004]],
 'formal_seeds':{'ladder':{'S':[51001,51002],'M':[52001,52002],'L':[53001,53002]},'regions':{'S':[61001,61002],'M':[62001,62002],'L':[63001,63002]}},
 'closures_min':{'short':10,'long':35},'horizon_extension_min':12,
 'geometry':'Two rails with end and internal rungs; or two local cycles linked by exactly two inter-region corridors. Bidirectional edges.',
 'coordinate_jitter_km':0.025,'path_count':3,
 'chargers':'Three geographically separated nodes; every chain first arrives at one, then visits varying endpoints. Single charger each.',
 'mission_pattern':'Seeded endpoints; first service to a facility, second service crosses to the opposite rail/region where possible; later services rotate among facilities and non-facilities.',
 'initial_soc_fraction':0.8,'baseline_charge_margin_kwh':0.003,
 'closure_target':'First corridor of the second mission of the first chain, selected before any disrupted optimization.',
 'attempts_per_base':20,'attempt_seed_increment':100,
 'validity':'Valid pre-disruption incumbent and task structure only. No quality, routing, difficulty or solver-completion filter.',
 'preference':'Original L1,L2,L3,L4,L5,L6','reference_budget_seconds':[1800,3600],
 'formal_solver_threads':1,'online_budget_seconds':600,
 'development_rule_changes':0,
}

def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def decision(m,pid,d,c): return {'mission_id':m['mission_id'],'uav_id':m['uav_id'],'held':False,'path_id':pid,'depart_min':d,'charge_blocks':c}

def construct(topology,scale,seed,index=1,development=False):
 rng=random.Random(seed); spec=CONFIG['scales'][scale]; n=spec['nodes']; left=(n+1)//2; right=n-left
 raw=[]
 if topology=='ladder':
  for side,count in enumerate((left,right)):
   for i in range(count): raw.append((-0.6+1.2*i/(count-1),(-0.22 if side==0 else 0.22)))
  edges={(i,i+1) for i in range(left-1)}|{(left+i,left+i+1) for i in range(right-1)}
  edges|={(0,left),(left-1,n-1),(left//2,left+right//2)}
 else:
  for side,count in enumerate((left,right)):
   for i in range(count):
    angle=2*math.pi*i/count; raw.append(((-0.4 if side==0 else 0.4)+.24*math.cos(angle),.3*math.sin(angle)))
  edges={(i,(i+1)%left) for i in range(left)}|{(left+i,left+(i+1)%right) for i in range(right)}
  edges|={(0,left+right//2),(left//2,left)}
 nodes=[{'vertiport_id':f'V{i+1:02d}','xy_km':[x+rng.uniform(-.025,.025),y+rng.uniform(-.025,.025)]} for i,(x,y) in enumerate(raw)]
 ids=[v['vertiport_id'] for v in nodes]; pos={v['vertiport_id']:v['xy_km'] for v in nodes}
 graph=nx.Graph(); graph.add_nodes_from(ids); corridors=[]; eids={}
 for ia,ib in sorted({tuple(sorted(e)) for e in edges}):
  a,b=ids[ia],ids[ib]; length=math.dist(pos[a],pos[b]); graph.add_edge(a,b,weight=length)
  for src,dst in ((a,b),(b,a)):
   cid=f'E_{src}_{dst}';eids[src,dst]=cid;corridors.append({'corridor_id':cid,'origin':src,'destination':dst,'distance_km':length,'geometry_xy_km':[pos[src],pos[dst]]})
 facilities=[ids[1],ids[left-1],ids[left+right//2]]
 nid=('DEV' if development else 'NEW')+f'_{topology}_{scale}{index:02d}'
 task={'record_id':nid,'schema_version':'arco_continuous_events_v1','model':copy.deepcopy(MODEL),
  'timing':{'departure_grid_min':1,'resource_window_min':1,'charge_block_min':5,'max_charge_blocks':3,'turnaround_min':5,'horizon_departure_min':240},
  'nodes':nodes,'corridors':corridors,'fleet':[],'missions':[],
  'resources':{'corridor':{c['corridor_id']:2 for c in corridors},'pad':{v:2 for v in ids},'charger':{v:int(v in facilities) for v in ids}},
  'baseline':{'decisions':[]},'intervention':{'resource_intervals':[],'initial_soc_overrides':{}}}
 cache={}
 def paths(src,dst,payload):
  if (src,dst) not in cache: cache[src,dst]=list(itertools.islice(nx.shortest_simple_paths(graph,src,dst,weight='weight'),3))
  result=[]
  for j,seq in enumerate(cache[src,dst]):
   p={'path_id':f'P{j+1}','origin':src,'destination':dst,'corridor_ids':[eids[a,b] for a,b in zip(seq,seq[1:])]};f=flight(task,p,payload);p.update(flight_min=f['flight_min'],energy_kwh=f['energy_kwh']);result.append(p)
  return result
 mid=0
 for u,length in enumerate(spec['chains']):
  uid=f'U{u+1:02d}'; first_dest=facilities[u%3]; choices=[v for v in ids if v!=first_dest];origin=rng.choice(choices); first=origin
  for j in range(length):
   if j==0: dest=first_dest
   elif j==1:
    opposite=ids[left:] if ids.index(origin)<left else ids[:left]
    dest=rng.choice([v for v in opposite if v!=origin])
   elif j%2==0: dest=rng.choice([v for v in facilities if v!=origin])
   else: dest=rng.choice([v for v in ids if v!=origin])
   mid+=1;payload=rng.choice([.25,.5]);m={'mission_id':f'M{mid:03d}','uav_id':uid,'sequence_index':j+1,'origin':origin,'destination':dest,'payload_kg':payload,'priority':'urgent' if rng.random()<.4 else 'routine','release_min':0,'due_min':240,'paths':paths(origin,dest,payload),'incoming':None}
   task['missions'].append(m);task['baseline']['decisions'].append(decision(m,'P1',0,0));origin=dest
  task['fleet'].append({'uav_id':uid,'initial_soc_kwh':.8*.0999,'battery_capacity_kwh':.0999,'reserve_kwh':.2*.0999,'available_min':rng.randint(0,3),'initial_vertiport':first})
 engine=Engine(task);calendar=Counter();baseline=[];specs={}
 for uid,chain in engine.chains.items():
  soc=engine.initial[uid];clock=engine.fleet[uid]['available_min'];reserve=engine.fleet[uid]['reserve_kwh']
  for j,m in enumerate(chain):
   arrival_soc=soc-engine.info[m['mission_id'],'P1']['energy_kwh']
   if arrival_soc<reserve-SOC_TOL: raise ValueError('baseline energy between facilities')
   needed=0
   for nxt in chain[j+1:]:
    needed+=engine.info[nxt['mission_id'],'P1']['energy_kwh']
    if task['resources']['charger'][nxt['destination']]>0:break
   c=0
   if task['resources']['charger'][m['destination']]>0 and j<len(chain)-1:
    c=max(0,math.ceil((reserve+needed+.003-arrival_soc-1e-9)/(.1*.88*5/60)))
   if c>3:raise ValueError('baseline charging duration')
   if arrival_soc+c*(.1*.88*5/60)>.0999+SOC_TOL:raise ValueError('baseline battery capacity')
   chosen=None
   for d in range(math.ceil(clock-1e-9),220):
    o=engine.option(m,'P1',d,c)
    if all(calendar[k]+num<=window_cap(task,*k,1) for k,num in o['blocks'].items()):chosen=o;break
   if chosen is None:raise ValueError('baseline scheduling horizon')
   baseline.append(decision(m,'P1',chosen['depart_min'],c));calendar.update(chosen['blocks']);clock=chosen['finish_min'];soc=arrival_soc+chosen['charge_kwh'];m['release_min']=max(0,chosen['depart_min']-rng.randint(0,2));m['due_min']=chosen['arrival_min']+rng.randint(3,8 if m['priority']=='urgent' else 15);specs[m['mission_id']]=chosen
 task['baseline']['decisions']=baseline;task['timing']['horizon_departure_min']=max(d['depart_min'] for d in baseline)+CONFIG['horizon_extension_min']
 before=Engine(task).verify(baseline)
 if not before['admissible']:raise ValueError(('incumbent',before['errors']))
 target=engine.chains['U01'][1];event=specs[target['mission_id']];kind,cid,s,e=event['intervals'][0]
 states={}
 for condition,duration in CONFIG['closures_min'].items():
  t=copy.deepcopy(task);t['record_id']=nid+'_'+condition;t['intervention']['resource_intervals']=[{'kind':'corridor','resource':cid,'start_min':math.floor(s),'end_min':math.floor(s)+duration,'capacity':0}];states[condition]=t
 meta={'network_id':nid,'topology':topology,'scale':scale,'seed':seed,'index':index,'development':development,'pre_incumbent_valid':True,'facilities':facilities,'affected_mission':target['mission_id'],'closed_corridor':cid,'closure_start_min':math.floor(s),'horizon_min':task['timing']['horizon_departure_min'],'missions':len(task['missions']),'chains':len(task['fleet']),'final_origins':sorted({chain[-1]['origin'] for chain in engine.chains.values()}),'incumbent_charge_blocks':sum(d['charge_blocks'] for d in baseline)}
 return states,meta

def generate(development=False):
 folder=OUT/('development' if development else 'formal');cells=CONFIG['development_cells'] if development else [(t,s,seed) for t,ss in CONFIG['formal_seeds'].items() for s,seeds in ss.items() for seed in seeds]
 records=[];counts=Counter()
 for topology,scale,base_seed in cells:
  counts[topology,scale]+=1;index=counts[topology,scale];attempts=[]
  for attempt in range(20):
   try:states,meta=construct(topology,scale,base_seed+100*attempt,index,development);break
   except ValueError as e:attempts.append({'attempt':attempt,'seed':base_seed+100*attempt,'reason':str(e)})
  else:records.append({'topology':topology,'scale':scale,'base_seed':base_seed,'unfilled':True,'attempts':attempts});continue
  meta.update(base_seed=base_seed,attempt=attempt,rejected_attempts=attempts);records.append(meta)
  for task in states.values():write((folder/'tasks' if development else OUT/'tasks')/(task['record_id']+'.json'),task)
  print(meta['network_id'],'attempt',attempt,'H',meta['horizon_min'],'facilities',meta['facilities'],'charges',meta['incumbent_charge_blocks'],flush=True)
 write(folder/'manifest.json',records)
 if not development:
  write(ROOT/'protocol/new_networks_frozen.json',CONFIG)
  write(ROOT/'protocol/new_task_hashes.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((OUT/'tasks').glob('*.json'))})

def develop(budget):
 rows=[]
 for p in sorted((OUT/'development/tasks').glob('*.json')):
  out=OUT/'development/references'/p.name
  if out.exists():r=read(out)
  else:r=Engine(read(p)).solve(budget=budget);write(out,r)
  task=read(p);e=Engine(task);score=e.verify(r['decisions']);rows.append({'record_id':p.stem,'optimal':r['optimal'],'proved_prefix':r['proved_prefix'],'seconds':r['total_seconds'],'holds':score['objective']['total_holds'],'reroutes':sum(ev.get('route_changed',False) for ev in score['events']),'charge_blocks':sum(d['charge_blocks'] for d in r['decisions']),'objective':r['objective']})
  write(OUT/'development/results.json',rows);print(rows[-1],flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['development','formal','develop']);p.add_argument('--budget',type=float,default=120);a=p.parse_args()
 if a.mode=='develop':develop(a.budget)
 else:generate(a.mode=='development')
