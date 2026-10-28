"""Limited action restrictions and inspectable paired event changes."""
import argparse,csv,json,sys
from new_networks import ROOT,OUT,Engine,read,write,csvout
from new_references import solve,metrics

def select():
 rows=list(csv.DictReader((ROOT/'results/new_pairs.csv').open(encoding='utf-8-sig')));selected=[]
 for topology in ('ladder','regions'):
  eligible=[r for r in rows if r['topology']==topology and r['observed_route_charge_change']=='True']
  eligible.sort(key=lambda r:('SML'.index(r['scale']),r['network_id']))
  if eligible:selected.append(eligible[0]['network_id']+'_long')
 config={'selection_rule':'For each topology, first S then M then L and ascending network ID with an observed short-to-long increase in both rerouting and charging changes. At most one long task per topology; fixed-route and fixed-charge diagnostics each. No network or generated model output is removed.','selected_tasks':selected,'restrictions':['incumbent_service_routes','incumbent_charge_counts'],'maximum_solves':4,'budget_seconds':1800,'service_prefix':'match the certified unrestricted reference urgent and total holds','selection_uses':'deterministic short/long reference actions only; before model output'}
 target=ROOT/'protocol/new_mechanism_subset.json'
 if target.exists() and read(target)!=config:raise RuntimeError('selected mechanism subset already frozen differently')
 write(target,config);return selected

def run():
 for rid in select():
  task=read(OUT/'tasks'/(rid+'.json'));ref=read(OUT/'references'/(rid+'.json'));e=Engine(task);service=[ref['objective'][k] for k in ('urgent_holds','total_holds')]
  for mode in ('routes','charges'):
   p=OUT/'mechanism_restrictions'/f'{rid}__{mode}.json'
   if p.exists():continue
   key='path_id' if mode=='routes' else 'charge_blocks';allowed=lambda o:o[key]==e.base[o['mission_id']][key]
   r=solve(task,budget=1800,allowed=allowed,service=service);r.update(restriction=mode,fixed_service=service)
   if r['phases'] and r['phases'][-1]['status']==2:r['interpretation']='change required to retain certified service prefix'
   elif r['optimal']:
    from continuous_engine import quality
    r['interpretation']='change required for reference quality, not service' if not quality(r['objective'],ref['objective']) else 'same reference quality attainable without this change class'
   else:r['interpretation']='unresolved within diagnostic budget'
   write(p,r);print(rid,mode,r['interpretation'],'seconds',round(r['total_seconds'],2),flush=True)

def charger_order(score):
 groups={}
 for event in score['resource_intervals']:
  if event['kind']=='charger':groups.setdefault(event['resource'],[]).append(event)
 return {k:[x['mission_id'] for x in sorted(v,key=lambda x:(x['start_min'],x['mission_id']))] for k,v in groups.items()}

def summarize():
 events=[];pair_events=[];restrictions=[]
 for p in sorted((OUT/'references').glob('*.json')):
  task=read(OUT/'tasks'/p.name);e=Engine(task);ref=read(p);score=e.verify(ref['decisions'])
  for ev in score['events']:events.append(ev)
 for m in read(OUT/'formal/manifest.json'):
  if m.get('unfilled'):continue
  nid=m['network_id'];ps=OUT/'references'/(nid+'_short.json');pl=OUT/'references'/(nid+'_long.json')
  if not ps.exists() or not pl.exists():continue
  s=Engine(read(OUT/'tasks'/ps.name)).verify(read(ps)['decisions']);l=Engine(read(OUT/'tasks'/pl.name)).verify(read(pl)['decisions']);sb={e['mission_id']:e for e in s['events']};lb={e['mission_id']:e for e in l['events']};so=charger_order(s);lo=charger_order(l)
  changed_orders=[]
  for facility in sorted(set(so)|set(lo)):
   common=set(so.get(facility,[]))&set(lo.get(facility,[]));a=[x for x in so.get(facility,[]) if x in common];b=[x for x in lo.get(facility,[]) if x in common]
   if a!=b:changed_orders.append(facility)
  for mid in sb:
   a,b=sb[mid],lb[mid]
   fields=('held','path_id','depart_min','charge_blocks','arrival_min','soc_arrival_kwh','soc_after_charge_kwh')
   changes=[f for f in fields if a.get(f)!=b.get(f)]
   if changes:pair_events.append({'network_id':nid,'mission_id':mid,'uav_id':a['uav_id'],'changed_fields':','.join(changes),'facilities_with_common_user_order_reversal':','.join(changed_orders),**{'short_'+f:a.get(f) for f in fields},**{'long_'+f:b.get(f) for f in fields}})
 for p in sorted((OUT/'mechanism_restrictions').glob('*.json')):
  r=read(p);restrictions.append({'record_id':r['record_id'],'restriction':r['restriction'],'optimal':r['optimal'],'proved_prefix':r['proved_prefix'],'seconds':r['total_seconds'],'interpretation':r['interpretation'],'last_status':r['phases'][-1]['status'] if r['phases'] else None,**(r['objective'] or {})})
 if events:
  write(ROOT/'results/new_reference_events.json',events)
 if pair_events:csvout(ROOT/'results/new_pair_event_changes.csv',pair_events)
 if restrictions:csvout(ROOT/'results/new_mechanism_restrictions.csv',restrictions)
 print('events',len(events),'paired_changes',len(pair_events),'restrictions',len(restrictions),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','summary']);a=p.parse_args();run() if a.mode=='run' else summarize()
