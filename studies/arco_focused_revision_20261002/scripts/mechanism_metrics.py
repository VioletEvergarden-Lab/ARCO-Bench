"""Transport/service metrics from the unchanged continuous-event verifier."""
import csv, json
from collections import Counter, defaultdict
from pathlib import Path
from preference_solver import ROOT, OLD, Engine, TIERS, QUALITY_TOL

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def csvout(path,rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader()
        for r in rows: w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})

def metrics(task, decisions, reference=None, source='', order=tuple(range(6))):
    eng=Engine(task); score=eng.verify(decisions); rid=task['record_id']
    row={'record_id':rid,'network_id':rid[:-2],'scale':rid.split('_')[1][0],'condition':rid[-1],
         'source':source,'admissible':score['admissible'],'errors':score['errors'],
         'urgent_demand':sum(m['priority']=='urgent' for m in task['missions']),'total_demand':len(task['missions'])}
    if not score['admissible']: return row
    events=[e for e in score['events'] if not e['held']]; base=eng.base
    held=[d['mission_id'] for d in decisions if d['held']]
    routed=[e for e in events if e['route_changed']]
    charged=[e for e in events if e['charge_blocks']!=base[e['mission_id']]['charge_blocks']]
    moved=[e for e in events if e['departure_shift_min']>1e-7]
    served=sorted(e['mission_id'] for e in events)
    row.update(urgent_served=sum(e['priority']=='urgent' for e in events),total_served=len(events),
               urgent_on_time=sum(e['priority']=='urgent' and e['tardiness_min']<=1e-7 for e in events),
               total_on_time=sum(e['tardiness_min']<=1e-7 for e in events),
               weighted_tardiness_min=score['objective'][TIERS[3]],max_tardiness_min=max((e['tardiness_min'] for e in events),default=0.),
               L3_hold_cost=1000*len(held),L3_route_cost=20*len(routed),
               L3_departure_cost=.2*sum(e['departure_shift_min'] for e in events),
               L3_charge_toggle_cost=10*sum((e['charge_blocks']>0)!=(base[e['mission_id']]['charge_blocks']>0) for e in events),
               L3_charge_block_cost=2*sum(abs(e['charge_blocks']-base[e['mission_id']]['charge_blocks']) for e in events),
               route_changes=len(routed),route_change_missions=[e['mission_id'] for e in routed],route_change_chains=sorted({e['uav_id'] for e in routed}),
               departure_changes=len(moved),charge_changes=len(charged),charge_change_missions=[e['mission_id'] for e in charged],charge_change_chains=sorted({e['uav_id'] for e in charged}),
               charge_blocks=sum(e['charge_blocks'] for e in events),flight_energy_kwh=sum(e['flight_energy_kwh'] for e in events),
               charge_energy_kwh=sum(e['charge_kwh'] for e in events),minimum_postflight_reserve_margin_kwh=min((e['reserve_margin_kwh'] for e in events),default=None),
               held_missions=held,served_missions=served,objective=score['objective'])
    assert abs(sum(row[k] for k in ['L3_hold_cost','L3_route_cost','L3_departure_cost','L3_charge_toggle_cost','L3_charge_block_cost'])-score['objective'][TIERS[2]])<1e-7
    if reference:
        ref=reference['objective']; refserved=sorted(d['mission_id'] for d in reference['decisions'] if not d['held'])
        first=next((j for j in order if abs(score['objective'][TIERS[j]]-ref[TIERS[j]])>QUALITY_TOL[j]+1e-10),None)
        row.update(reference_quality=first is None,first_mismatch_tier='L'+str(first+1) if first is not None else None,
                   first_mismatch_objective=TIERS[first] if first is not None else None,
                   first_mismatch_absolute_difference=abs(score['objective'][TIERS[first]]-ref[TIERS[first]]) if first is not None else 0.,
                   first_mismatch_signed_difference=score['objective'][TIERS[first]]-ref[TIERS[first]] if first is not None else 0.,
                   same_service_set_as_reference=served==refserved,
                   energy_difference_same_service_kwh=score['objective'][TIERS[5]]-ref[TIERS[5]] if served==refserved else None)
    return row

def extract():
    out=ROOT/'results/mechanism'; out.mkdir(parents=True,exist_ok=True)
    scores=[r for r in read(OLD/'evaluation/scores.json') if r['layer']=='network']
    rows=[]
    for path in sorted((OLD/'networks/tasks').glob('NET_*.json')):
        task=read(path); rid=path.stem; ref=read(OLD/'networks/references'/path.name)
        rows.append(metrics(task,ref['decisions'],ref,'reference'))
        for r in scores:
            if r['record_id']!=rid: continue
            if r.get('decisions') is not None: rows.append(metrics(task,r['decisions'],ref,r['source']))
            else: rows.append({'record_id':rid,'network_id':rid[:-2],'scale':rid.split('_')[1][0],'condition':rid[-1],'source':r['source'],'admissible':False,'status':r['status'],'errors':r['errors']})
    write(out/'service_energy_metrics.json',rows); csvout(out/'service_energy_metrics.csv',rows)
    bounds={r['record_id']:r for r in read(OLD/'coordination_bounds/results.json')}
    proof=[]
    for rid in ('NET_S02_C','NET_M01_B','NET_M01_C','NET_M03_B'):
        task=read(OLD/'networks/tasks'/f'{rid}.json'); eng=Engine(task); ref=read(OLD/'networks/references'/f'{rid}.json'); det=read(OLD/'networks/candidates'/f'{rid}.json'); g=det['G']['decisions']; by={d['mission_id']:d for d in g}
        costs=defaultdict(float)
        for d in g:
            prior=eng.base[d['mission_id']]
            costs[d['uav_id']]+=1000 if d['held'] else 20*(d['path_id']!=prior['path_id'])+.2*abs(d['depart_min']-prior['depart_min'])+10*((d['charge_blocks']>0)!=(prior['charge_blocks']>0))+2*abs(d['charge_blocks']-prior['charge_blocks'])
        lengths={u:len(chain) for u,chain in eng.chains.items()}; b=bounds[rid]
        refby={d['mission_id']:d for d in ref['decisions']}
        changed=[mid for mid in sorted(by) if any(by[mid][k]!=refby[mid][k] for k in ('held','path_id','depart_min','charge_blocks'))]
        assert changed==sorted(b['changed_missions']) and len(changed)==b['distance_upper_bound']
        refscore=eng.verify(ref['decisions']); r4score=eng.verify(det['R4']['result']['decisions'])
        first=next(j for j in range(6) if abs(r4score['objective'][TIERS[j]]-refscore['objective'][TIERS[j]])>QUALITY_TOL[j]+1e-10)
        assert first<=3 and det['R4']['result']['proved_prefix']>first and r4score['objective'][TIERS[first]]>refscore['objective'][TIERS[first]]+QUALITY_TOL[first]
        assert b['distance_lower_bound']==5 and eng.verify(g)['admissible'] and refscore['admissible']
        row={'record_id':rid,'distance_lower_bound':b['distance_lower_bound'],'distance_upper_bound':b['distance_upper_bound'],'witness_changed_missions':b['changed_missions'],'witness_changed_chains':b['changed_uavs'],'witness_chain_count':len(b['changed_uavs']),'chain_lengths':lengths,'greedy_L3_by_chain':dict(costs),'reference_L3':ref['objective']['repair_distance'],'necessary_minimum_changed_chains':2,'exact_minimum_changed_chains':2 if rid=='NET_M01_B' else None}
        if rid=='NET_S02_C':
            assert max(lengths.values())==4
            row['exclusion']='Any reference-quality plan differs from G on at least five missions, whereas every UAV chain contains at most four missions.'
        elif rid in ('NET_M01_B','NET_M01_C'):
            assert by['M008']['held'] and eng.missions['M008']['priority']=='urgent' and eng.missions['M008']['uav_id']=='U02' and lengths['U02']==4 and ref['objective']['urgent_holds']==0
            row.update(forced_recovery_mission='M008',forced_recovery_chain='U02',forced_recovery_chain_length=4,
                       exclusion='Zero urgent holds requires restoring M008 on U02. Changing only this four-mission chain cannot meet the certified five-mission distance lower bound.')
        else:
            eligible=[u for u,n in lengths.items() if n>=5]
            assert eligible==['U01']
            outside=sum(c for u,c in costs.items() if u!='U01'); assert outside>ref['objective']['repair_distance']+QUALITY_TOL[2]
            row.update(only_chain_long_enough='U01',fixed_other_chain_L3=outside,
                       exclusion='Only U01 has five missions; fixing all other chains at G already incurs L3=39.4, exceeding reference L3=22 before adding any nonnegative U01 cost.')
        proof.append(row)
    write(out/'cross_chain_necessity.json',proof); csvout(out/'cross_chain_necessity.csv',proof)
    wanted=[('deepseek','NET_S01_B',3,8.),('deepseek','NET_S03_C',3,12.),('deepseek','NET_L03_C',3,3.4),('deepseek','NET_L01_C',4,40.),('luna','NET_L04_A',3,.4),('luna','NET_M01_B',3,1.),('luna','NET_M04_B',3,7.),('luna','NET_L01_C',3,.2)]
    gaps=[]
    for source,rid,tier,gap in wanted:
        row=next(r for r in rows if r['record_id']==rid and r['source']==source)
        assert row['admissible'] and row['first_mismatch_tier']=='L'+str(tier) and abs(row['first_mismatch_signed_difference']-gap)<1e-7
        gaps.append({k:row[k] for k in ['record_id','source','urgent_demand','urgent_served','urgent_on_time','total_demand','total_served','weighted_tardiness_min','first_mismatch_tier','first_mismatch_objective','first_mismatch_signed_difference']})
    csvout(out/'eight_first_gaps.csv',gaps); write(out/'eight_first_gaps.json',gaps)
    misses=[]
    for path in sorted((OLD/'networks/candidates').glob('NET_*.json')):
        d=read(path)
        if d['R4']['quality']: continue
        r=d['R4']['result']; row=next(x for x in rows if x['record_id']==path.stem and x['source']=='R4')
        misses.append({'record_id':path.stem,'all_six_stages_proven':r['optimal'],'proved_prefix':r['proved_prefix'],'last_stage_status':r['phases'][-1]['status'],'first_mismatch_tier':row['first_mismatch_tier'],'first_mismatch_signed_difference':row['first_mismatch_signed_difference'],'interpretation':'certified fixed-radius quality exclusion' if r['optimal'] else 'search unfinished; no radius infeasibility conclusion'})
    csvout(out/'R4_miss_status.csv',misses); write(out/'R4_miss_status.json',misses)
    summary={}
    for source in ('reference','G','R4','deepseek','luna'):
        subset=[r for r in rows if r['source']==source]; good=[r for r in subset if r['admissible']]
        summary[source]={'records':len(subset),'admissible':len(good),'urgent_served':sum(r['urgent_served'] for r in good),'urgent_demand_of_admissible':sum(r['urgent_demand'] for r in good),'urgent_on_time':sum(r['urgent_on_time'] for r in good),'total_served':sum(r['total_served'] for r in good),'total_demand_of_admissible':sum(r['total_demand'] for r in good),'reference_quality':sum(r['reference_quality'] for r in good),'route_changes':sum(r['route_changes'] for r in good),'departure_changes':sum(r['departure_changes'] for r in good)}
    summary['R4_misses']={'total':len(misses),'certified':sum(r['all_six_stages_proven'] for r in misses),'unfinished':[r['record_id'] for r in misses if not r['all_six_stages_proven']]}
    write(out/'summary.json',summary); print(json.dumps(summary,indent=2))

if __name__=='__main__': extract()
