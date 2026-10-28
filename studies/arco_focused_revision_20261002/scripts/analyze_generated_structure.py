"""Read-only diagnosis of generated repairs on the frozen paired networks.

No optimization or provider calls. Missing terminals stay pending/in-flight;
Missing candidate outputs are separate from returned-plan violations.
"""
from pathlib import Path
import argparse,csv,hashlib,json,statistics
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from new_networks import ROOT,OUT,Engine,read,write
from continuous_engine import compare,quality,QUALITY_TOL,buckets,point_bucket,cap_at
from study_common import TIERS

METHODS=('G','R4','Full-MILP','Iter-R4','R_frac')
FAILURE_ATTEMPT='NEW_regions_L02_long__deepseek__r1'

def csvout(path,rows):
 if not rows:return
 path.parent.mkdir(parents=True,exist_ok=True);fields=list(dict.fromkeys(k for r in rows for k in r))
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)

def profile(engine,score):
 events=[e for e in score.get('events',[]) if not e['held']];base=engine.base
 return {'served':len(events),'urgent_served':sum(e.get('priority')=='urgent' for e in events),'urgent_demand':sum(m['priority']=='urgent' for m in engine.missions.values()),'urgent_on_time':sum(e.get('priority')=='urgent' and e.get('tardiness_min',float('inf'))<=1e-7 for e in events),'reroutes':sum(e.get('route_changed',False) for e in events),'rerouted_missions':[e['mission_id'] for e in events if e.get('route_changed')],'charge_blocks':sum(e.get('charge_blocks',0) for e in events),'charge_changes':sum(e.get('charge_blocks')!=base[e['mission_id']]['charge_blocks'] for e in events),'charge_changed_missions':[e['mission_id'] for e in events if e.get('charge_blocks')!=base[e['mission_id']]['charge_blocks']],'minimum_reserve_margin_kwh':min((e['reserve_margin_kwh'] for e in events if 'reserve_margin_kwh' in e),default=None),'energy_kwh':sum(e.get('flight_energy_kwh',0) for e in events),'max_lateness_min':max((e.get('tardiness_min',0) for e in events),default=None)}

def first_gap(vector,reference):
 if not vector:return None,None
 for k,tol in zip(TIERS,QUALITY_TOL):
  if abs(vector[k]-reference[k])>tol+1e-10:return k,vector[k]-reference[k]
 return None,None

def failure_class(terminal,score):
 error=terminal.get('error') or {}
 if terminal.get('status')=='no_answer' and 'http_status' not in terminal and not terminal.get('raw_text'):return 'no_candidate_output'
 if terminal.get('http_status')==402 or (isinstance(error,dict) and error.get('code')=='credit_balance_exhausted'):return 'no_candidate_output'
 if terminal.get('incomplete_details',{}) and terminal['incomplete_details'].get('reason')=='max_output_tokens':return 'output_token_limit_no_complete_plan'
 if terminal.get('http_status') not in (None,200):return 'provider_http_failure'
 if terminal.get('transport_error'):return 'transport_failure'
 if score is not None and not score['admissible']:return 'returned_plan_invalid'
 if score is not None and score['admissible']:return 'valid_plan'
 if terminal.get('errors'):return 'schema_or_parse_failure'
 if terminal.get('identity_accepted') is False and terminal.get('http_status')==200:return 'model_identity_mismatch'
 return 'no_complete_plan'

def resource_window_witness(engine,score,load):
 """Attribute the verifier's overloaded booking window to actual flight events."""
 width=load['width_min'];start=load['bucket']*width;end=start+width
 contributors=[];events={e['mission_id']:e for e in score.get('events',[]) if not e['held']}
 if load['kind'] in ('corridor','charger'):
  for interval in score.get('resource_intervals',[]):
   if interval['kind']!=load['kind'] or interval['resource']!=load['resource']:continue
   booked=list(buckets(interval['start_min'],interval['end_min'],width))
   if load['bucket'] not in booked:continue
   event=events[interval['mission_id']]
   contributors.append({'mission_id':interval['mission_id'],'uav_id':interval['uav_id'],'path_id':event['path_id'],'depart_min':event['depart_min'],'route_changed':event['route_changed'],'actual_entry_min':interval['start_min'],'actual_exit_min':interval['end_min'],'reservation_windows_min':[[b*width,(b+1)*width] for b in booked]})
  points={start,end}
  points.update(t for v in contributors for t in (v['actual_entry_min'],v['actual_exit_min']) if start<t<end)
  points.update(t for v in engine.task['intervention']['resource_intervals'] if v['kind']==load['kind'] and v['resource']==load['resource'] for t in (v['start_min'],v['end_min']) if start<t<end)
  spans=[]
  for a,b in zip(sorted(points),sorted(points)[1:]):
   midpoint=(a+b)/2;active=[v['mission_id'] for v in contributors if v['actual_entry_min']<=midpoint<v['actual_exit_min']]
   spans.append({'start_min':a,'end_min':b,'mission_ids':active,'actual_count':len(active),'actual_capacity':cap_at(engine.task,load['kind'],load['resource'],midpoint)})
  return {'window_start_min':start,'window_end_min':end,'contributors':contributors,'maximum_actual_occupancy_within_window':max((s['actual_count'] for s in spans),default=0),'actual_capacity_violation_within_window':any(s['actual_count']>s['actual_capacity'] for s in spans),'actual_occupancy_spans':spans}
 # Pad windows count movements, so preserve each takeoff or landing separately.
 for event in events.values():
  mission=engine.missions[event['mission_id']];movements=[(mission['origin'],event['depart_min'],'service_takeoff'),(mission['destination'],event['arrival_min'],'service_landing')]
  if mission.get('incoming'):movements.extend([(mission['incoming']['origin'],event['incoming_start_min'],'incoming_takeoff'),(mission['origin'],event['incoming_arrival_min'],'incoming_landing')])
  for node,t,kind in movements:
   if node==load['resource'] and point_bucket(t,width)==load['bucket']:contributors.append({'mission_id':event['mission_id'],'uav_id':event['uav_id'],'movement':kind,'actual_time_min':t,'reservation_windows_min':[[start,end]]})
 return {'window_start_min':start,'window_end_min':end,'contributors':contributors}

def invalid_details(engine,score):
 details=[];reserve_failed_chains=set()
 for e in score.get('events',[]):
  if e['held']:continue
  if e.get('reserve_margin_kwh',0)<-1e-6:
   details.append({'kind':'reserve_deficit',**e,'reserve_required_kwh':engine.fleet[e['uav_id']]['reserve_kwh'],'first_reserve_violation_on_chain':e['uav_id'] not in reserve_failed_chains});reserve_failed_chains.add(e['uav_id'])
  if e.get('soc_after_charge_kwh',0)>engine.fleet[e['uav_id']]['battery_capacity_kwh']+1e-6:details.append({'kind':'battery_overcharge','mission_id':e['mission_id'],'uav_id':e['uav_id'],'soc_after_charge_kwh':e['soc_after_charge_kwh']})
 for r in score.get('window_loads',[]):
  if r['count']>r['capacity']:details.append({**r,'violation_type':'resource_window_capacity',**resource_window_witness(engine,score,r)})
 for uid,chain in engine.chains.items():
  events={e['mission_id']:e for e in score.get('events',[])};previous=None;held=False
  for m in chain:
   e=events.get(m['mission_id'])
   if not e:continue
   if e['held']:held=True;continue
   if held:details.append({'kind':'served_after_held_prefix','mission_id':m['mission_id'],'uav_id':uid})
   start=e.get('incoming_start_min') if e.get('incoming_start_min') is not None else e.get('depart_min')
   if previous is not None and start<previous-1e-7:details.append({'kind':'chain_time_overlap','mission_id':m['mission_id'],'uav_id':uid,'start_min':start,'previous_finish_min':previous})
   previous=e.get('finish_min')
 return details

def analyze(online,output):
 output.mkdir(parents=True,exist_ok=True);bindings=read(online/'BINDINGS.json');terminal_snapshot={}
 for b in bindings:
  p=online/'attempts'/b['attempt_id']/'TERMINAL.json'
  if p.exists():terminal_snapshot[b['attempt_id']]=read(p)
 tasks={p.stem:read(p) for p in sorted((OUT/'tasks').glob('*.json'))};engines={rid:Engine(t) for rid,t in tasks.items()};refs={rid:read(OUT/'references'/(rid+'.json')) for rid in tasks}
 ref_profiles={rid:profile(engines[rid],engines[rid].verify(r['decisions'])) for rid,r in refs.items()}
 deterministic=[];det_by={};alignment=[]
 for rid,e in engines.items():
  for method in METHODS:
   p=ROOT/'results/new_comparison/runs'/f'{rid}__{method}.json'
   if not p.exists():continue
   r=read(p);s=e.verify(r['decisions']);miss,gap=first_gap(s['objective'],refs[rid]['objective']);row={'record_id':rid,'method':method,'admissible':s['admissible'],'objective_matches_saved':s['objective']==r['objective'],'task_hash_matches':hashlib.sha256((OUT/'tasks'/(rid+'.json')).read_bytes()).hexdigest()==r['task_sha256'],'service_target':s['admissible'] and all(s['objective'][k]==refs[rid]['objective'][k] for k in TIERS[:2]),'reference_quality':s['admissible'] and quality(s['objective'],refs[rid]['objective']),'first_miss':miss,'first_gap':gap,'stop_reason':r['stop_reason'],'total_seconds':r['total_seconds'],'global_optimal':r['global_optimal'],**profile(e,s)}
   alignment.append(row);det_by[rid,method]=r
   if not (row['admissible'] and row['objective_matches_saved'] and row['task_hash_matches']):raise RuntimeError(('deterministic alignment mismatch',rid,method))
 for method in METHODS:
  subset=[r for r in alignment if r['method']==method];deterministic.append({'method':method,'completed':len(subset),'admissible':sum(r['admissible'] for r in subset),'service_target':sum(r['service_target'] for r in subset),'reference_quality':sum(r['reference_quality'] for r in subset),'first_miss_counts':dict(Counter(r['first_miss'] for r in subset if r['first_miss']))})
 rows=[];plans={};violations=[];differences=[];case_plans=[]
 for b in bindings:
  aid=b['attempt_id'];rid=b['record_id'];terminal=terminal_snapshot.get(aid);row={k:b[k] for k in ('attempt_id','record_id','network_id','public_record_id','provider','repeat','rank','condition')};row.update(terminal_observed=terminal is not None,status=terminal.get('status') if terminal else 'in_flight' if (online/'attempts'/aid/'SUBMISSION_INTENT.json').exists() else 'pending',admissible=None,service_target=None,reference_quality=None)
  if terminal is None:row['outcome_class']=row['status'];rows.append(row);continue
  e=engines[rid];s=e.verify(terminal['decisions']) if terminal.get('decisions') is not None else None
  row.update(outcome_class=failure_class(terminal,s),http_status=terminal.get('http_status'),provider_error_code=(terminal.get('error') or {}).get('code'),finish_reason=terminal.get('finish_reason'),incomplete_details=terminal.get('incomplete_details'),available_seconds=terminal.get('available_seconds'),response_seconds=terminal.get('response_seconds'),validation_errors=s['errors'] if s is not None else terminal.get('errors'),usage=terminal.get('usage'))
  if s is not None:
   if s['admissible']!=terminal['admissible'] or s['objective']!=terminal.get('objective'):raise RuntimeError(('model score mismatch',aid))
   row.update(admissible=s['admissible'],service_target=s['admissible'] and all(s['objective'][k]==refs[rid]['objective'][k] for k in TIERS[:2]),reference_quality=s['admissible'] and quality(s['objective'],refs[rid]['objective']),**profile(e,s));miss,gap=first_gap(s['objective'],refs[rid]['objective']);row.update(first_miss=miss,first_gap=gap)
   plans[aid]={'decisions':terminal['decisions'],'score':s}
   if not s['admissible']:
    violations.extend({'attempt_id':aid,'record_id':rid,**d} for d in invalid_details(e,s))
   else:
    bd={d['mission_id']:d for d in refs[rid]['decisions']}
    for d in terminal['decisions']:
     fields=[k for k in ('held','path_id','depart_min','charge_blocks') if d[k]!=bd[d['mission_id']][k]]
     if fields:differences.append({'attempt_id':aid,'record_id':rid,'mission_id':d['mission_id'],'uav_id':d['uav_id'],'fields':fields,'reference_quality':row['reference_quality'],'model_decision':d,'reference_decision':bd[d['mission_id']]})
  if b['repeat']==1 and rid in ('NEW_regions_S02_long','NEW_ladder_L02_long'):
   case_plans.append({**row,'reference':ref_profiles[rid],'model_events':s['events'] if s is not None else None,'reference_events':e.verify(refs[rid]['decisions'])['events']})
  rows.append(row)
 main={(r['network_id'],r['condition'],r['provider']):r for r in rows if r['repeat']==1};paired=[]
 for m in read(OUT/'formal/manifest.json'):
  if m.get('unfilled'):continue
  nid=m['network_id'];shortref,longref=ref_profiles[nid+'_short'],ref_profiles[nid+'_long']
  for provider in ('deepseek','luna'):
   sr,lr=main[nid,'short',provider],main[nid,'long',provider];r={'network_id':nid,'topology':m['topology'],'scale':m['scale'],'provider':provider,'short_attempt':sr['attempt_id'],'long_attempt':lr['attempt_id'],'short_status':sr['status'],'long_status':lr['status'],'short_outcome':sr['outcome_class'],'long_outcome':lr['outcome_class'],'reference_wait_to_reroute':shortref['reroutes']==0 and longref['reroutes']>0,'reference_route_charge_switch':longref['reroutes']>shortref['reroutes'] and longref['charge_changes']>shortref['charge_changes']}
   if not sr['terminal_observed'] or not lr['terminal_observed']:r['pair_status']='not_yet_complete'
   elif not sr.get('admissible') or not lr.get('admissible'):r['pair_status']='plan_unavailable_or_invalid'
   else:
    r.update(pair_status='both_valid',both_reference_quality=sr['reference_quality'] and lr['reference_quality'],both_service_target=sr['service_target'] and lr['service_target'],short_reroutes=sr['reroutes'],long_reroutes=lr['reroutes'],short_charge_blocks=sr['charge_blocks'],long_charge_blocks=lr['charge_blocks'],observed_wait_to_reroute=sr['reroutes']==0 and lr['reroutes']>0,observed_route_charge_switch=lr['reroutes']>sr['reroutes'] and lr['charge_changes']>sr['charge_changes'],reference_action_counts_match=all(r0[key]==r1[key] for r0,r1 in ((sr,shortref),(lr,longref)) for key in ('reroutes','charge_blocks')))
   paired.append(r)
 providers={}
 for provider in ('deepseek','luna'):
  subset=[r for r in rows if r['provider']==provider and r['repeat']==1];done=[r for r in subset if r['terminal_observed']];valid=[r for r in subset if r.get('admissible')];pr=[r for r in paired if r['provider']==provider]
  providers[provider]={'scheduled_main':len(subset),'terminal_main':len(done),'not_yet_terminal':len(subset)-len(done),'outcomes':dict(Counter(r['outcome_class'] for r in subset)),'valid_plans':len(valid),'reference_quality':sum(r['reference_quality'] for r in valid),'service_target':sum(r['service_target'] for r in valid),'complete_valid_pairs':sum(r['pair_status']=='both_valid' for r in pr),'reference_quality_pairs':sum(r.get('both_reference_quality',False) for r in pr),'observed_wait_to_reroute_pairs':sum(r.get('observed_wait_to_reroute',False) for r in pr),'observed_route_charge_pairs':sum(r.get('observed_route_charge_switch',False) for r in pr)}
 providers_all={provider:{'scheduled':sum(r['provider']==provider for r in rows),'outcomes':dict(Counter(r['outcome_class'] for r in rows if r['provider']==provider)),'valid_plans':sum(bool(r.get('admissible')) for r in rows if r['provider']==provider),'reference_quality':sum(bool(r.get('reference_quality')) for r in rows if r['provider']==provider)} for provider in ('deepseek','luna')}
 summary={'as_of_utc':datetime.now(timezone.utc).isoformat(),'scheduled_attempts':len(rows),'terminal_attempts':sum(r['terminal_observed'] for r in rows),'pending_attempts':sum(r['status']=='pending' for r in rows),'in_flight_attempts':sum(r['status']=='in_flight' for r in rows),'terminal_outcomes':dict(Counter(r['outcome_class'] for r in rows if r['terminal_observed'])),'deterministic':deterministic,'providers_main':providers,'providers_all':providers_all,'score_alignment_checked':True,'returned_plan_violations':sum(r.get('outcome_class')=='returned_plan_invalid' for r in rows),'invalid_event_count':len(violations),'paired_scope':'First formal attempts only. Repetitions do not create independent networks. Pending and in-flight requests are not failures.','route_and_charge_scope':'Actions in returned plans relative to the incumbent; observed response does not identify a model internal reasoning process.'}
 write(output/'summary.json',summary);write(output/'mechanism_cases.json',case_plans);csvout(output/'per_attempt.csv',rows);csvout(output/'main_pairs.csv',paired);csvout(output/'deterministic_alignment.csv',alignment);csvout(output/'decision_differences.csv',differences);write(output/'decision_differences.json',differences)
 write(output/'invalid_events.json',violations)
 failure_cases=[]
 for row in rows:
  if row.get('outcome_class')!='returned_plan_invalid':continue
  aid=row['attempt_id'];rid=row['record_id'];e=engines[rid];s=plans[aid]['score'];reference_score=e.verify(refs[rid]['decisions']);selected=[v for v in violations if v['attempt_id']==aid];uids={v['uav_id'] for w in selected for v in w.get('contributors',[])}|{w['uav_id'] for w in selected if 'uav_id' in w}
  failure_cases.append({'attempt_id':aid,'record_id':rid,'provider':row['provider'],'repeat':row['repeat'],'verifier_errors':s['errors'],'violations':selected,'model_chain_events':[v for v in s['events'] if v['uav_id'] in uids],'reference_chain_events':[v for v in reference_score['events'] if v['uav_id'] in uids],'reference_role':'Existing certified reference; no new generation or optimization.'})
 write(output/'failure_cases.json',failure_cases)
 failure_case=None
 if FAILURE_ATTEMPT in terminal_snapshot and FAILURE_ATTEMPT in plans:
  rid=terminal_snapshot[FAILURE_ATTEMPT]['record_id'];e=engines[rid];s=plans[FAILURE_ATTEMPT]['score'];selected=[v for v in violations if v['attempt_id']==FAILURE_ATTEMPT];reference_score=e.verify(refs[rid]['decisions']);involved={v['mission_id'] for w in selected for v in w.get('contributors',[])};model_decisions={d['mission_id']:d for d in plans[FAILURE_ATTEMPT]['decisions']};reference_decisions={d['mission_id']:d for d in refs[rid]['decisions']}
  failure_case={'attempt_id':FAILURE_ATTEMPT,'record_id':rid,'provider':'deepseek','repeat':1,'verifier_errors':s['errors'],'violations':selected,'returned_plan_structure':profile(e,s),'contributing_decisions':[{'mission_id':mid,'model':model_decisions[mid],'reference':reference_decisions[mid]} for mid in sorted(involved)],'reference_resource_intervals':[v for v in reference_score['resource_intervals'] if v['mission_id'] in involved and any(v['kind']==w['kind'] and v['resource']==w['resource'] for w in selected)],'interpretation':'The returned reroutes and charging decisions leave three cross-UAV reservations in one capacity-two corridor window. This is a booking-window coordination failure; the witness does not imply three aircraft occupy the corridor simultaneously.','reference_role':'Existing certified reference only; no corrected generation or new optimization.'}
  write(output/'failure_case.json',failure_case)
 print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--online',type=Path,default=ROOT/'online/new_generation');p.add_argument('--output',type=Path,default=ROOT/'results/generated_structure');a=p.parse_args();analyze(a.online,a.output)
