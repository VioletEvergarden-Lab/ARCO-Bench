"""Rebuild paired-study tables and vector figures, without optimization or API use."""
import copy,csv,hashlib,itertools,statistics
from new_networks import ROOT,OUT,Engine,read,write
from new_references import summarize
from new_mechanisms import summarize as event_summary,charger_order
from new_figures import pairs,case

def run():
 summarize();event_summary();checks=[];charger_rows=[]
 for m in read(OUT/'formal/manifest.json'):
  if m.get('unfilled'):continue
  nid=m['network_id'];ts={c:read(OUT/'tasks'/(nid+'_'+c+'.json')) for c in ('short','long')}
  a,b=copy.deepcopy(ts['short']),copy.deepcopy(ts['long'])
  a.pop('record_id');b.pop('record_id');a['intervention']['resource_intervals'][0].pop('end_min');b['intervention']['resource_intervals'][0].pop('end_min');assert a==b,(nid,'pair changes more than closure duration')
  scores={}
  for cond,t in ts.items():
   r=read(OUT/'references'/(nid+'_'+cond+'.json'));s=Engine(t).verify(r['decisions']);assert r['optimal'] and r['proved_prefix']==6 and s['admissible'];scores[cond]=s
  orders={c:charger_order(s) for c,s in scores.items()};reversals=0;comparable=0
  for facility in set(orders['short'])|set(orders['long']):
   x,y=orders['short'].get(facility,[]),orders['long'].get(facility,[]);common=set(x)&set(y)
   for first,second in itertools.combinations(sorted(common),2):
    # Only orders between different chains express cross-UAV sharing.
    e=Engine(ts['short'])
    if e.missions[first]['uav_id']==e.missions[second]['uav_id']:continue
    comparable+=1
    if (x.index(first)<x.index(second))!=(y.index(first)<y.index(second)):reversals+=1
  charger_rows.append({'network_id':nid,'common_cross_chain_charging_pairs':comparable,'reversed_pairs':reversals})
  checks.append({'network_id':nid,'only_closure_duration_differs':True,'both_references_complete_and_valid':True})
 rows=list(csv.DictReader((ROOT/'results/new_reference_metrics.csv').open(encoding='utf-8-sig')));paired=list(csv.DictReader((ROOT/'results/new_pairs.csv').open(encoding='utf-8-sig')))
 stats={'tasks':len(rows),'networks':len(paired),'certified_references':sum(r['optimal']=='True' for r in rows),'wait_to_reroute_pairs':sum(r['observed_wait_to_reroute']=='True' for r in paired),'route_charge_pairs':sum(r['observed_route_charge_change']=='True' for r in paired),'served':sum(int(r['served']) for r in rows),'urgent_served':sum(int(r['urgent_served']) for r in rows),'short_urgent_on_time':sum(int(r['urgent_on_time']) for r in rows if r['record_id'].endswith('short')),'long_urgent_on_time':sum(int(r['urgent_on_time']) for r in rows if r['record_id'].endswith('long')),'short_reroutes':sum(int(r['short_reroutes']) for r in paired),'long_reroutes':sum(int(r['long_reroutes']) for r in paired),'short_charging_blocks':sum(int(r['short_charge_blocks']) for r in paired),'long_charging_blocks':sum(int(r['long_charge_blocks']) for r in paired),'reference_seconds_total':sum(float(r['reference_seconds']) for r in rows),'reference_seconds_median':statistics.median(float(r['reference_seconds']) for r in rows),'reference_seconds_max':max(float(r['reference_seconds']) for r in rows),'reference_timings_are_online_comparisons':False,'charger_order_comparable_cross_chain_pairs':sum(r['common_cross_chain_charging_pairs'] for r in charger_rows),'charger_order_reversed_pairs':sum(r['reversed_pairs'] for r in charger_rows),'charger_order_pairs':charger_rows}
 bindings=read(OUT/'generation_prepared/BINDINGS.json');assert len(bindings)==96 and len({r['attempt_id'] for r in bindings})==96
 for row in bindings:assert hashlib.sha256((ROOT/row['request_path']).read_bytes()).hexdigest()==row['request_sha256']
 hashes=read(ROOT/'protocol/new_task_hashes.json')
 for filename,h in hashes.items():assert hashlib.sha256((OUT/'tasks'/filename).read_bytes()).hexdigest()==h
 write(ROOT/'results/new_summary.json',stats);write(ROOT/'results/new_checks.json',{'pair_checks':checks,'valid_reference_count':len(rows),'frozen_task_hashes_match':True,'prepared_request_hashes_match':True,'distinct_planned_attempts':96,'checks':'pair identity; all reference verification; completed six-layer certificates; frozen task and request identities'});pairs();case();print(stats)

if __name__=='__main__':run()
