"""Offline references with a single capped continuation of certified prefixes."""
from pathlib import Path
import argparse, copy, csv, hashlib, json, math, random, sys, time
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from scipy.sparse import csr_matrix,vstack
from new_networks import ROOT,OLD,OUT,CONFIG,Engine,read,write,csvout,canonical
from continuous_engine import compare,EPS_TIME
from study_common import TIERS
from solver_backend import solve as mip,VERSION

def solve(task,budget=1800,previous=None,allowed=None,service=None):
 start=time.perf_counter();e=Engine(task);b=e.build(allowed=allowed);A,lb,ub=b['A'],b['lb'],b['ub']
 def add(c,value,tol):
  nonlocal A,lb,ub
  A=vstack([A,csr_matrix(c.reshape(1,-1))],format='csr');lb=np.append(lb,value-tol);ub=np.append(ub,value+tol)
 if service is not None:
  for j,v in enumerate(service):add(b['costs'][j],v,0)
 def to_x(plan):
  x=np.zeros(b['variables'])
  for d in plan:
   mid=d['mission_id'];i=b['holds'][mid] if d['held'] else next(i for i in b['indices'][mid] if all(b['meta'][i][k]==d[k] for k in ('path_id','depart_min','charge_blocks')));x[i]=1
  return x
 phases=[];completed=0;last=best=None;best_vector=None
 if previous:
  if previous.get('decisions') is not None:
   last=best=to_x(previous['decisions']);best_vector=e.verify(previous['decisions'])['objective']
  for phase in previous['phases']:
   if phase['status']!=0:break
   j=TIERS.index(phase['tier']);tol=0 if j<2 else 1e-5 if j in (3,4) else EPS_TIME
   add(b['costs'][j],phase['upper_bound']*b['scales'][j],tol);phases.append(copy.deepcopy(phase));completed+=1
 if last is None:
  g=e.greedy();gs=e.verify(g)
  if gs['admissible'] and (allowed is None or all(d['held'] or allowed(d) for d in g)) and (service is None or all(gs['objective'][TIERS[j]]==v for j,v in enumerate(service))):last=best=to_x(g);best_vector=gs['objective']
 build=time.perf_counter()-start;bounds,proof=e.service_lower_bounds()
 for j in range(completed,6):
  remain=budget-(time.perf_counter()-start)
  if remain<=0:break
  c=b['costs'][j].copy();nearest=np.rint(c);c[np.abs(c-nearest)<1e-9]=nearest[np.abs(c-nearest)<1e-9];constant=0
  if j==2:
   c-=1000*b['scales'][j]*b['costs'][1];constant=1000*round(phases[1]['upper_bound'])
  clock=time.perf_counter()
  lower=service[j] if service is not None and j<2 else bounds[j] if j<2 else None
  if j<2 and last is not None and abs(c@last-lower)<1e-8:
   from types import SimpleNamespace
   r=SimpleNamespace(status=0,x=last,mip_dual_bound=float(lower),mip_gap=0.,message='public service bound')
  else:r=mip(c,A,lb,ub,remain,last)
  x=np.rint(r.x) if r.x is not None else None
  phase={'tier':TIERS[j],'status':int(r.status),'status_text':r.message,'upper_bound':float(c@x/b['scales'][j]+constant) if x is not None else None,'lower_bound':float(r.mip_dual_bound/b['scales'][j]+constant) if r.mip_dual_bound is not None else None,'mip_gap':r.mip_gap,'seconds':time.perf_counter()-clock}
  phases.append(phase)
  if x is not None:
   s=e.verify(e.extract(b,x))
   if not s['admissible']:raise RuntimeError((task['record_id'],s['errors']))
   if best is None or compare(s['objective'],best_vector)<0:best=x;best_vector=s['objective']
   last=x
  if r.status!=0 or x is None:break
  value=float(c@x);value=float(round(value)) if j<3 else value;tol=0 if j<2 else 1e-5 if j in (3,4) else EPS_TIME;add(c,value,tol)
 optimal=len(phases)==6 and all(p['status']==0 for p in phases);chosen=last if optimal else best;decisions=e.extract(b,chosen) if chosen is not None else None
 elapsed=time.perf_counter()-start
 return {'record_id':task['record_id'],'optimal':optimal,'proved_prefix':sum(p['status']==0 for p in phases),'phases':phases,'decisions':decisions,'objective':e.verify(decisions)['objective'] if decisions is not None else None,'total_seconds':elapsed+(previous.get('total_seconds',0) if previous else 0),'segment_seconds':elapsed,'build_seconds':build,'budget_seconds':budget,'previous_segment_seconds':previous.get('total_seconds',0) if previous else 0,'continued_certified_prefix':completed,'variables':b['variables'],'solver':'HiGHS '+VERSION,'solver_threads':1,'prefix_policy':'Only proven prefixes fixed; unproved phase retains lower and upper bounds; no task dropped for an incomplete reference.','service_bounds':bounds,'service_bound_proof':proof}

def reference_job(p):
 task=read(p);target=OUT/'references'/p.name
 if target.exists():return p.stem
 first=OUT/'reference_segments'/('first_'+p.name)
 r=read(first) if first.exists() else solve(task,1800)
 if not first.exists():write(first,r)
 if not r['optimal']:
  remain=max(0,3600-r['total_seconds'])
  r2=solve(task,remain,previous=r);write(OUT/'reference_segments'/('continued_'+p.name),r2);r=r2
 write(target,r);print(p.stem,'optimal',r['optimal'],'prefix',r['proved_prefix'],'seconds',round(r['total_seconds'],2),flush=True)
 return p.stem

def run(limit=None,workers=1):
 paths=sorted((OUT/'tasks').glob('*.json'))
 if limit:paths=[p for p in paths if limit in p.stem]
 if workers==1:
  for p in paths:reference_job(p)
 else:
  with ProcessPoolExecutor(max_workers=workers) as pool:list(pool.map(reference_job,paths))

def metrics(task,result):
 e=Engine(task);s=e.verify(result['decisions']);events=[x for x in s['events'] if not x['held']];base=e.base
 return {'record_id':task['record_id'],'optimal':result['optimal'],'proved_prefix':result['proved_prefix'],'reference_seconds':result['total_seconds'],'served':len(events),'urgent_served':sum(x['priority']=='urgent' for x in events),'urgent_on_time':sum(x['priority']=='urgent' and x['tardiness_min']<=1e-7 for x in events),'route_changes':sum(x['route_changed'] for x in events),'departure_changes':sum(x['departure_shift_min']>1e-7 for x in events),'charge_changes':sum(x['charge_blocks']!=base[x['mission_id']]['charge_blocks'] for x in events),'charge_blocks':sum(x['charge_blocks'] for x in events),'charge_chains':','.join(sorted({x['uav_id'] for x in events if x['charge_blocks']!=base[x['mission_id']]['charge_blocks']})),'reroute_chains':','.join(sorted({x['uav_id'] for x in events if x['route_changed']})),'flight_energy_kwh':sum(x['flight_energy_kwh'] for x in events),'minimum_reserve_margin_kwh':min(x['reserve_margin_kwh'] for x in events),'maximum_lateness_min':max(x['tardiness_min'] for x in events),**s['objective']}

def summarize():
 rows=[];pairs=[]
 for p in sorted((OUT/'references').glob('*.json')):rows.append(metrics(read(OUT/'tasks'/p.name),read(p)))
 if rows:csvout(ROOT/'results/new_reference_metrics.csv',rows)
 by={r['record_id']:r for r in rows}
 for meta in read(OUT/'formal/manifest.json'):
  if meta.get('unfilled'):continue
  nid=meta['network_id'];short=by.get(nid+'_short');long=by.get(nid+'_long')
  if not short or not long:continue
  pairs.append({**{k:meta[k] for k in ('network_id','topology','scale','seed','attempt')},'short_certified':short['optimal'],'long_certified':long['optimal'],'short_reroutes':short['route_changes'],'long_reroutes':long['route_changes'],'short_charge_blocks':short['charge_blocks'],'long_charge_blocks':long['charge_blocks'],'short_charge_changes':short['charge_changes'],'long_charge_changes':long['charge_changes'],'short_served':short['served'],'long_served':long['served'],'short_urgent_on_time':short['urgent_on_time'],'long_urgent_on_time':long['urgent_on_time'],'energy_delta_kwh':long['flight_energy_kwh']-short['flight_energy_kwh'],'observed_wait_to_reroute':short['route_changes']==0 and long['route_changes']>0,'observed_route_charge_change':long['route_changes']>short['route_changes'] and long['charge_changes']>short['charge_changes']})
 if pairs:csvout(ROOT/'results/new_pairs.csv',pairs)
 print('summarized',len(rows),'tasks,',len(pairs),'pairs',flush=True)

def prepare_requests():
 tasks=sorted((OUT/'tasks').glob('*.json'));ids=[p.stem for p in tasks];random.Random(64117).shuffle(ids);mapping={rid:f'TASK_{j:03d}' for j,rid in enumerate(ids,1)}
 instruction=(OLD/'continuous_public_instructions.md').read_text(encoding='utf-8');system='You are solving a UAV integrated-repair optimization task. Return only one JSON object that exactly follows the requested schema. Do not use Markdown or explanatory text.'
 settings={'deepseek':{'max_tokens':128000,'model':'deepseek-v4-pro','temperature':0.0},'luna':{'background':True,'max_output_tokens':128000,'model':'gpt-5.6-luna','reasoning':{'context':'current_turn','effort':'max','mode':'standard'},'store':False,'stream':False,'tools':[]}}
 folder=OUT/'generation_prepared';write(folder/'ARCHIVED_SETTINGS.json',{'settings':settings,'status':'prepared_only_not_sent','source':'arco_closing_study/run_models.py SETTINGS','requires_before_execution':'Confirm current authorized endpoint/model support and A-C frozen execution; no POST performed by this script.'})
 selected={m['network_id']:('short' if m['index']==1 else 'long') for m in read(OUT/'formal/manifest.json') if not m.get('unfilled')}
 planned=[]
 for rid in ids:
  task=read(OUT/'tasks'/(rid+'.json'));task['record_id']=mapping[rid];task['model'].pop('slot_min',None);user=instruction+'\n\nPublic task:\n\n'+canonical(task).decode();write(folder/'public_tasks'/(rid+'.json'),task)
  (folder/'public_inputs').mkdir(parents=True,exist_ok=True);(folder/'public_inputs'/(rid+'.txt')).write_text(user,encoding='utf-8')
  nid=rid.rsplit('_',1)[0];condition=rid.rsplit('_',1)[1];repeats=3 if selected[nid]==condition else 1
  for repeat in range(1,repeats+1):
   for provider in ('deepseek','luna'):
    body=copy.deepcopy(settings[provider]);body['messages' if provider=='deepseek' else 'input']=([{'role':'system','content':system}] if provider=='deepseek' else [])+[{'role':'user','content':user}];aid=f'{rid}__{provider}__r{repeat}';rp=folder/'requests'/(aid+'.json');write(rp,body)
    planned.append({'attempt_id':aid,'record_id':rid,'network_id':nid,'public_record_id':mapping[rid],'condition':condition,'provider':provider,'repeat':repeat,'request_path':str(rp.relative_to(ROOT)).replace('\\','/'),'request_sha256':hashlib.sha256(rp.read_bytes()).hexdigest(),'public_payload_sha256':hashlib.sha256(user.encode()).hexdigest(),'status':'prepared_not_sent'})
 planned.sort(key=lambda b:(b['repeat'],ids.index(b['record_id']),('deepseek','luna').index(b['provider'])))
 for rank,b in enumerate(planned,1):b['rank']=rank
 write(folder/'BINDINGS.json',planned);csvout(folder/'BINDINGS.csv',planned);write(ROOT/'protocol/new_generation_manifest.json',{'formal_tasks':len(tasks),'base_networks':len(selected),'planned_attempts':len(planned),'main_attempts':len(tasks)*2,'additional_repeats':len(planned)-len(tasks)*2,'repetition_condition_by_network':selected,'balance':'Within each topology and scale, base index 1 short; index 2 long. Same selected task has three independent planned attempts per model.','order_seed':64117,'two_providers_interleaved':True,'requests_sent':0,'reference_or_mechanism_labels_in_payload':False})
 print('Prepared',len(planned),'requests; POSTs=0',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['solve','summary','requests']);p.add_argument('--contains');p.add_argument('--workers',type=int,default=1);a=p.parse_args()
 if a.mode=='solve':run(a.contains,a.workers)
 elif a.mode=='summary':summarize()
 else:prepare_requests()
