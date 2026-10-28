"""Existing-record paired analysis and three booking/one energy witnesses.
No optimization, API calls, changed rules, or manuscript edits.
"""
import csv,json,math,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WS=ROOT.parent
FOCUS=WS/'arco_focused_revision_20261002'
OLD=WS/'arco_closing_study'
OUT=ROOT/'analysis'
sys.path.insert(0,str(FOCUS/'scripts'))
from analyze_generated_structure import resource_window_witness
from continuous_engine import Engine,quality,SOC_TOL
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def write(name,x):(OUT/name).write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def rel(p):return str(p.relative_to(WS)).replace('\\','/')
def profile(task,decisions):
 b={d['mission_id']:d for d in task['baseline']['decisions']}
 ds=[d for d in decisions if not d['held']]
 rer=[d['mission_id'] for d in ds if d['path_id']!=b[d['mission_id']]['path_id']]
 chg=[d['mission_id'] for d in ds if d['charge_blocks']!=b[d['mission_id']]['charge_blocks']]
 return {'served':len(ds),'reroutes':len(rer),'charge_changed_missions':len(chg),
         'total_charge_blocks':sum(d['charge_blocks'] for d in ds),'rerouted_ids':rer,'charge_changed_ids':chg}
def flatten_csv(name,rows):
 with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader()
  for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 attempts={r['attempt_id']:r for r in csv.DictReader((FOCUS/'results/generated_structure/per_attempt.csv').open(encoding='utf-8-sig'))}
 manifest=read(FOCUS/'new_networks/formal/manifest.json')
 manifest.sort(key=lambda x:(x['topology'],{'S':0,'M':1,'L':2}[x['scale']],x['network_id']))
 rows=[];cache={};refprofiles={};same_quality_witnesses=[]
 for m in manifest:
  nid=m['network_id']
  for cond in ('short','long'):
   rid=nid+'_'+cond;tp=FOCUS/'new_networks/tasks'/f'{rid}.json';rp=FOCUS/'new_networks/references'/f'{rid}.json'
   task,ref=read(tp),read(rp);assert ref['optimal'] and ref['proved_prefix']==6
   cache[rid]=(task,ref);refprofiles[rid]=profile(task,ref['decisions'])
  sr,lr=(refprofiles[nid+'_'+c] for c in ('short','long'))
  refwait=sr['reroutes']==0 and lr['reroutes']>0
  refjoint=lr['reroutes']>sr['reroutes'] and lr['charge_changed_missions']>sr['charge_changed_missions']
  for provider in ('reference','deepseek','luna'):
   row={'network_id':nid,'topology':m['topology'],'scale':m['scale'],'source':provider,
        'reference_wait_to_reroute':refwait,'reference_joint_route_charge':refjoint}
   profiles={};all_valid=True
   for cond in ('short','long'):
    rid=nid+'_'+cond;task,ref=cache[rid]
    if provider=='reference':
     p=FOCUS/'new_networks/references'/f'{rid}.json';decisions=ref['decisions']
     state='admissible';outcome='certified_reference';admissible=True;rq=True;aid=''
    else:
     aid=f'{rid}__{provider}__r1';a=attempts[aid];p=FOCUS/'online/new_generation/attempts'/aid/'TERMINAL.json';terminal=read(p)
     decisions=terminal.get('decisions');state=terminal['status'];outcome=a['outcome_class'];admissible=terminal.get('admissible') is True
     rq=admissible and quality(terminal['objective'],ref['objective'])
     assert rq==(a['reference_quality']=='True')
    all_valid=all_valid and admissible
    row.update({cond+'_record_id':rid,cond+'_attempt_id':aid,cond+'_status':state,cond+'_outcome':outcome,
                cond+'_admissible':admissible,cond+'_reference_quality':rq,cond+'_source_record':rel(p)})
    if decisions is not None:
     pr=profile(task,decisions);profiles[cond]=pr
     for k,v in pr.items():row[cond+'_'+k]=v
     if provider!='reference':
      for key,oldkey in [('reroutes','reroutes'),('charge_changed_missions','charge_changes'),('total_charge_blocks','charge_blocks')]:
       assert pr[key]==int(attempts[aid][oldkey]),(aid,key)
     refby={d['mission_id']:d for d in ref['decisions']}
     changed={d['mission_id']:[k for k in ('held','path_id','depart_min','charge_blocks') if d[k]!=refby[d['mission_id']][k]]
              for d in decisions}
     changed={k:v for k,v in changed.items() if v}
     row[cond+'_decisions_differing_from_reference']=changed
     row[cond+'_reference_decision_identity']=not changed
     if provider!='reference' and rq and changed:
      modelby={d['mission_id']:d for d in decisions}
      same_quality_witnesses.append({'record_id':rid,'provider':provider,'attempt_id':aid,
       'source_record':rel(p),'admissible':admissible,'reference_quality':rq,
       'reference_objective':ref['objective'],'candidate_objective':terminal['objective'],
       'differences':[{'mission_id':mid,'fields':fields,'reference':refby[mid],'candidate':modelby[mid]} for mid,fields in changed.items()]})
    else:
     for k in ('served','reroutes','charge_changed_missions','total_charge_blocks','rerouted_ids','charge_changed_ids','decisions_differing_from_reference','reference_decision_identity'):row[cond+'_'+k]=None
   row['both_admissible']=all_valid
   row['pair_status']='both_admissible' if all_valid else 'unavailable_or_infeasible'
   row['wait_to_reroute']=profiles['short']['reroutes']==0 and profiles['long']['reroutes']>0 if all_valid else None
   row['joint_route_charge']=profiles['long']['reroutes']>profiles['short']['reroutes'] and profiles['long']['charge_changed_missions']>profiles['short']['charge_changed_missions'] if all_valid else None
   rows.append(row)
 assert len(rows)==36
 flatten_csv('paired_candidates.csv',rows)
 summary={'definitions':{
  'scope':'Twelve base networks x reference/DeepSeek/Luna; only scheduled first responses, never repeated attempts.',
  'reroutes':'Served missions with service path different from incumbent.',
  'charge_changed_missions':'Served missions with charging-block count different from incumbent; not total charging blocks.',
  'wait_to_reroute':'short reroutes = 0 and long reroutes > 0.',
  'joint_route_charge':'Both long rerouted-mission count and long changed-charging-mission count exceed short.',
  'invalid':'Counts may describe submitted infeasible decisions; transition labels require both conditions admissible. Missing plans have null counts, never zero.'},'sources':{}}
 for provider in ('reference','deepseek','luna'):
  rs=[r for r in rows if r['source']==provider];good=[r for r in rs if r['both_admissible']]
  ps={'base_networks':12,'both_admissible_pairs':len(good)}
  for kind,refkey in [('wait_to_reroute','reference_wait_to_reroute'),('joint_route_charge','reference_joint_route_charge')]:
   population=[r for r in rs if r[refkey]];eligible=[r for r in population if r['both_admissible']]
   hit=[r for r in eligible if r[kind]]
   ps[kind]={'reference_population':len(population),'evaluable_reference_pairs':len(eligible),
             'reproduced':len(hit),'all_reference_denominator':f'{len(hit)}/{len(population)}',
             'conditional_denominator':f'{len(hit)}/{len(eligible)}','reference_networks':[r['network_id'] for r in population],
             'not_evaluable':[r['network_id'] for r in population if not r['both_admissible']],
             'evaluable_disagreements':[r['network_id'] for r in eligible if not r[kind]]}
  ps['nontransition_pairs_retained']=[r['network_id'] for r in rs if not r['reference_wait_to_reroute']]
  ps['admissible_conditions_with_different_reference_decisions']=[r[c+'_record_id'] for r in rs for c in ('short','long') if r[c+'_admissible'] and not r[c+'_reference_decision_identity']]
  ps['first_response_outcomes']=dict(Counter(r[c+'_outcome'] for r in rs for c in ('short','long')))
  summary['sources'][provider]=ps
 write('paired_summary.json',summary)
 write('same_quality_different_decisions.json',same_quality_witnesses)

 # Replay three stored plans under their unchanged task rules.
 oldrow=next(r for r in read(OLD/'evaluation/scores.json') if r['record_id']=='NET_L04_A' and r['source']=='deepseek')
 witnesses=[]
 for rid in ('NET_L04_A','NEW_regions_L01_long','NEW_regions_L02_long'):
  if rid=='NET_L04_A':
   tp=OLD/'networks/tasks'/f'{rid}.json';task=read(tp);decisions=oldrow['decisions'];savedscore=oldrow['score'];sp=OLD/'evaluation/scores.json'
  else:
   task,_=cache[rid];sp=FOCUS/'online/new_generation/attempts'/f'{rid}__deepseek__r1/TERMINAL.json'
   term=read(sp);decisions=term['decisions'];savedscore={'errors':term['errors']}
  e=Engine(task);s=e.verify(decisions);assert s['errors']==savedscore['errors'],(rid,s['errors'],savedscore['errors'])
  bad=[w for w in s['window_loads'] if w['count']>w['capacity']]
  witness={'record_id':rid,'source':'deepseek','source_record':rel(sp),'admissible':s['admissible'],
           'verifier_errors':s['errors'],'booking_violations':[{**w,**resource_window_witness(e,s,w)} for w in bad],
           'any_continuous_capacity_error':any('ACTUAL_CAPACITY' in x for x in s['errors'])}
  witnesses.append(witness)
 write('reservation_failures.json',{'rule':'Each touched half-open booking window consumes one reservation; sweep uses the original cap_at and intervals. No alternate verifier or reference was computed.','cases':witnesses})

 # Fixed-state energy arithmetic, retaining original reserve tolerance.
 task,ref=cache['NEW_regions_S02_long'];e=Engine(task);s=e.verify(ref['decisions']);assert s['admissible']
 ev={x['mission_id']:x for x in s['events']};pre,last=ev['M008'],ev['M009']
 B=1000*pre['soc_arrival_kwh'];E=1000*last['flight_energy_kwh'];R=1000*e.fleet['U03']['reserve_kwh'];tol=SOC_TOL*1000
 gain=task['model']['charger_input_power_w']*task['model']['charging_efficiency']*task['timing']['charge_block_min']/60
 capacity=e.fleet['U03']['battery_capacity_kwh']*1000
 deficit=R+E-B-gain
 energy={'record_id':'NEW_regions_S02_long','uav_id':'U03','precharge_mission':'M008','detour_mission':'M009','path_id':last['path_id'],
  'scope':'Fixed M008 arrival SOC and M009 P2 route; energy arithmetic only, not a different optimized chain.',
  'SOC_TOL_kWh':SOC_TOL,'SOC_TOL_Wh':tol,'reserve_Wh':R,'precharge_Wh':B,'detour_energy_Wh':E,'battery_capacity_Wh':capacity,'gain_per_5min_block_Wh':gain,
  'extra_energy_required_strict_Wh':R+E-B,'extra_energy_required_verifier_Wh':R+E-B-tol,
  'one_block_shortfall_strict_Wh':deficit,'one_block_shortfall_after_tolerance_Wh':deficit-tol,
  'one_block_shortfall_fraction_of_detour_percent':100*deficit/E,
  'required_detour_reduction_with_tolerance_percent':100*(deficit-tol)/E,
  'one_block_equivalent_thresholds':{
    'minimum_precharge_strict_Wh':R+E-gain,'minimum_precharge_verifier_Wh':R+E-gain-tol,
    'maximum_detour_energy_strict_Wh':B+gain-R,'maximum_detour_energy_verifier_Wh':B+gain-R+tol,
    'maximum_reserve_strict_Wh':B+gain-E,'maximum_reserve_verifier_Wh':B+gain-E+tol},
  'block_cases':[{'blocks':k,'SOC_before_M009_Wh':B+k*gain,'SOC_at_M009_arrival_Wh':B+k*gain-E,
                 'reserve_margin_Wh':B+k*gain-E-R,'passes_energy_with_SOC_TOL':B+k*gain-E>=R-tol,
                 'within_battery_capacity':B+k*gain<=capacity+tol} for k in (0,1,2)],
  'actual_reference_timing':{'M008_arrival_min':pre['arrival_min'],'charge_start_min':pre['charge_start_min'],'charge_finish_min':pre['finish_min'],
    'M009_depart_min':last['depart_min'],'H_departure_min':task['timing']['horizon_departure_min'],'M009_arrival_min':last['arrival_min'],
    'M009_due_min':e.missions['M009']['due_min'],'tardiness_min':last['tardiness_min']},
  'actual_reference_charge_intervals':[x for x in s['resource_intervals'] if x['kind']=='charger' and x['mission_id']=='M008'],
  'actual_reference_admissible':s['admissible'],'actual_reference_errors':s['errors']}
 write('regions_S02_energy_thresholds.json',energy)
 print(json.dumps({'pairs':{p:{'both_admissible':v['both_admissible_pairs'],'wait':v['wait_to_reroute']['all_reference_denominator'],'wait_cond':v['wait_to_reroute']['conditional_denominator'],'joint':v['joint_route_charge']['all_reference_denominator'],'joint_cond':v['joint_route_charge']['conditional_denominator'],'different_decisions_conditions':len(v['admissible_conditions_with_different_reference_decisions'])} for p,v in summary['sources'].items()},
  'failures':[{r['record_id']:[(w['count'],w['capacity'],w['maximum_actual_occupancy_within_window']) for w in r['booking_violations']]} for r in witnesses],
  'energy':{k:energy[k] for k in ('SOC_TOL_Wh','one_block_shortfall_strict_Wh','one_block_shortfall_after_tolerance_Wh','one_block_shortfall_fraction_of_detour_percent')}},indent=2))
if __name__=='__main__':main()

